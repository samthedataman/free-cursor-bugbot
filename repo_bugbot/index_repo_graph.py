#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Iterable


IGNORE_DIRS = {
    ".git",
    ".repo-bugbot",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "coverage",
}

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "sitemap.xml",
}

INDEX_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".html",
    ".css",
}

IMPORT_RE = re.compile(
    r"""(?:
        import\s+(?:type\s+)?(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]
        |from\s+['"]([^'"]+)['"]\s+import
        |require\(\s*['"]([^'"]+)['"]\s*\)
        |import\(\s*['"]([^'"]+)['"]\s*\)
    )""",
    re.VERBOSE,
)
EXPORT_RE = re.compile(
    r"\bexport\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
)
TS_SYMBOL_RE = re.compile(
    r"\b(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
)
ROUTE_DECORATOR_RE = re.compile(r"@\w+\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
FASTAPI_ROUTER_RE = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
EXPRESS_ROUTE_RE = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
ENV_RE = re.compile(
    r"""(?:
        os\.getenv\(\s*['"]([A-Z0-9_]+)['"]
        |process\.env\.([A-Z0-9_]+)
        |import\.meta\.env\.([A-Z0-9_]+)
        |\$\{?([A-Z][A-Z0-9_]{2,})\}?
    )""",
    re.VERBOSE,
)
SERVICE_RE = re.compile(r"^\s*-\s*name:\s*([A-Za-z0-9_.-]+)\s*$")
ENV_KEY_RE = re.compile(r"^\s*-\s*key:\s*([A-Z0-9_]+)\s*$")


def is_ignored_path_part(part: str) -> bool:
    return (
        part in IGNORE_DIRS
        or part.startswith(".venv")
        or part.endswith(".egg-info")
        or part.endswith(".dist-info")
    )


def run_git(repo: Path, args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL)


def iter_repo_files(repo: Path) -> list[Path]:
    try:
        raw = run_git(repo, ["ls-files", "-co", "--exclude-standard"])
        candidates = [repo / line for line in raw.splitlines() if line.strip()]
    except Exception:
        candidates = []
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if not is_ignored_path_part(d)]
            for name in files:
                candidates.append(Path(root) / name)
    results: list[Path] = []
    for path in candidates:
        rel_parts = path.relative_to(repo).parts
        if any(is_ignored_path_part(part) for part in rel_parts):
            continue
        if path.name in SKIP_FILENAMES:
            continue
        if path.suffix.lower() not in INDEX_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
        except OSError:
            continue
        results.append(path)
    return sorted(set(results))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def json_meta(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def init_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(
        """
        PRAGMA journal_mode=WAL;
        DROP TABLE IF EXISTS edges;
        DROP TABLE IF EXISTS nodes;
        CREATE TABLE nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            key TEXT NOT NULL,
            path TEXT,
            name TEXT,
            meta TEXT NOT NULL DEFAULT '{}',
            UNIQUE(type, key)
        );
        CREATE TABLE edges (
            src INTEGER NOT NULL,
            dst INTEGER NOT NULL,
            type TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}',
            UNIQUE(src, dst, type)
        );
        CREATE INDEX idx_nodes_type_key ON nodes(type, key);
        CREATE INDEX idx_nodes_path ON nodes(path);
        CREATE INDEX idx_edges_src ON edges(src);
        CREATE INDEX idx_edges_dst ON edges(dst);
        """
    )
    return con


class GraphWriter:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.cache: dict[tuple[str, str], int] = {}

    def node(self, node_type: str, key: str, *, path: str | None = None, name: str | None = None, meta: dict[str, Any] | None = None) -> int:
        cache_key = (node_type, key)
        if cache_key in self.cache:
            return self.cache[cache_key]
        self.con.execute(
            "INSERT OR IGNORE INTO nodes(type, key, path, name, meta) VALUES(?,?,?,?,?)",
            (node_type, key, path, name, json_meta(meta or {})),
        )
        row = self.con.execute("SELECT id FROM nodes WHERE type=? AND key=?", (node_type, key)).fetchone()
        node_id = int(row[0])
        self.cache[cache_key] = node_id
        return node_id

    def edge(self, src: int, dst: int, edge_type: str, meta: dict[str, Any] | None = None) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO edges(src, dst, type, meta) VALUES(?,?,?,?)",
            (src, dst, edge_type, json_meta(meta or {})),
        )


def rel(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix()


def module_to_path_candidates(importer: str, spec: str) -> list[str]:
    if not spec.startswith("."):
        return []
    base = Path(importer).parent
    target = (base / spec).as_posix()
    stripped = re.sub(r"/+", "/", target)
    candidates = [stripped]
    for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
        candidates.append(stripped + ext)
    for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
        candidates.append(stripped.rstrip("/") + "/index" + ext)
    return candidates


def parse_python_symbols(text: str) -> list[tuple[str, str, int]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(("function", node.name, node.lineno))
        elif isinstance(node, ast.ClassDef):
            symbols.append(("class", node.name, node.lineno))
    return symbols


def parse_ts_symbols(text: str) -> list[tuple[str, str, int]]:
    symbols: list[tuple[str, str, int]] = []
    line_offsets: list[int] = []
    pos = 0
    for line in text.splitlines(True):
        line_offsets.append(pos)
        pos += len(line)
    for match in TS_SYMBOL_RE.finditer(text):
        line = 1 + sum(1 for offset in line_offsets if offset <= match.start())
        symbols.append(("symbol", match.group(1), line))
    return symbols


def index_file(repo: Path, path: Path, writer: GraphWriter, file_nodes: dict[str, int]) -> None:
    relative = rel(repo, path)
    text = read_text(path)
    file_id = writer.node(
        "file",
        relative,
        path=relative,
        name=path.name,
        meta={"extension": path.suffix.lower(), "size": len(text)},
    )
    file_nodes[relative] = file_id

    symbol_parser = parse_python_symbols if path.suffix == ".py" else parse_ts_symbols
    if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        for kind, name, line in symbol_parser(text):
            symbol_id = writer.node("symbol", f"{relative}::{name}", path=relative, name=name, meta={"kind": kind, "line": line})
            writer.edge(file_id, symbol_id, "defines", {"line": line})

    for match in EXPORT_RE.finditer(text):
        export_name = match.group(1)
        export_id = writer.node("export", f"{relative}::{export_name}", path=relative, name=export_name)
        writer.edge(file_id, export_id, "exports")

    for match in IMPORT_RE.finditer(text):
        spec = next((group for group in match.groups() if group), "")
        if not spec:
            continue
        import_id = writer.node("import", spec, name=spec)
        writer.edge(file_id, import_id, "imports")

    for regex in (ROUTE_DECORATOR_RE, FASTAPI_ROUTER_RE, EXPRESS_ROUTE_RE):
        for method, route in regex.findall(text):
            route_key = f"{method.upper()} {route}"
            route_id = writer.node("route", route_key, name=route_key)
            writer.edge(file_id, route_id, "registers_route")

    for match in ENV_RE.finditer(text):
        env_name = next((group for group in match.groups() if group), "")
        if not env_name or len(env_name) < 3:
            continue
        env_id = writer.node("env", env_name, name=env_name)
        writer.edge(file_id, env_id, "references_env")

    if path.name == "render.yaml":
        current_service = ""
        service_id = None
        for line in text.splitlines():
            service_match = SERVICE_RE.match(line)
            if service_match:
                current_service = service_match.group(1)
                service_id = writer.node("service", current_service, name=current_service)
                writer.edge(file_id, service_id, "declares_service")
            env_match = ENV_KEY_RE.match(line)
            if env_match:
                env_id = writer.node("env", env_match.group(1), name=env_match.group(1))
                writer.edge(file_id, env_id, "declares_env", {"service": current_service})
                if service_id:
                    writer.edge(service_id, env_id, "has_env")


def resolve_import_edges(repo: Path, writer: GraphWriter, file_nodes: dict[str, int]) -> None:
    imports = writer.con.execute(
        """
        SELECT f.id, f.key, i.key
        FROM nodes f
        JOIN edges e ON e.src = f.id AND e.type = 'imports'
        JOIN nodes i ON i.id = e.dst
        WHERE f.type = 'file'
        """
    ).fetchall()
    known = set(file_nodes)
    for file_id, importer, spec in imports:
        for candidate in module_to_path_candidates(str(importer), str(spec)):
            if candidate in known:
                writer.edge(int(file_id), file_nodes[candidate], "imports_file", {"specifier": spec})
                break


def index_tests(writer: GraphWriter, file_nodes: dict[str, int]) -> None:
    for path, node_id in file_nodes.items():
        if "/tests/" in path or path.startswith("tests/") or re.search(r"(test_|\.test\.|\.spec\.)", path):
            writer.edge(node_id, writer.node("tag", "test_file", name="test_file"), "has_tag")
            for other_path, other_id in file_nodes.items():
                stem = Path(other_path).stem.replace("test_", "")
                if stem and stem in path and other_id != node_id:
                    writer.edge(node_id, other_id, "tests")


def main() -> int:
    parser = argparse.ArgumentParser(description="Index repository relationships into a local SQLite graph.")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--db", default=".repo-bugbot/graph.sqlite", help="SQLite graph DB path")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    db = Path(args.db)
    if not db.is_absolute():
        db = repo / db
    con = init_db(db)
    writer = GraphWriter(con)
    file_nodes: dict[str, int] = {}
    files = iter_repo_files(repo)
    for path in files:
        index_file(repo, path, writer, file_nodes)
    resolve_import_edges(repo, writer, file_nodes)
    index_tests(writer, file_nodes)
    con.commit()
    counts = dict(con.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall())
    con.close()
    if not args.quiet:
        print(json.dumps({"db": str(db), "files": len(files), "nodes": counts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
