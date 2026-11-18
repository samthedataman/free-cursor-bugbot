"""Read committed Git objects without checking out or executing a project."""

from __future__ import annotations

import posixpath
import re
import subprocess
from pathlib import Path

from .diff_impact import classify_risks
from .index_repo_graph import IMPORT_RE, module_to_path_candidates

SLUG = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
REFERENCE = re.compile(
    rf"https?://github\.com/(?P<url_repo>{SLUG})/(?:issues|pull)/(?P<url_num>[1-9]\d*)"
    rf"|(?<![\w/#])(?:(?P<repo>{SLUG}))?#(?P<num>[1-9]\d*)\b"
)
GIT_OPTIONS = [
    "--no-pager",
    "--literal-pathspecs",
    "-c",
    "core.quotepath=false",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "log.showSignature=false",
]
DIFF = [
    "diff",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--find-renames",
    "--submodule=short",
]
PATCH_LIMIT = 96_000


def git(repo: Path, *args: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *GIT_OPTIONS, "-C", str(repo), *args],
        input=input_data,
        check=False,
        capture_output=True,
        timeout=120,
    )
    if result.returncode:
        message = result.stderr.decode(errors="replace").strip()
        raise ValueError(message[:500] or "Git could not read this repository.")
    return result.stdout


def text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def root(path: str | Path) -> Path:
    return Path(
        text(git(Path(path), "rev-parse", "--show-toplevel")).rstrip("\n")
    ).resolve()


def revision(repo: Path, ref: str) -> str:
    return text(
        git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    ).strip()


def comparison(repo: Path, head: str, base: str | None) -> tuple[str, str]:
    head = revision(repo, head)
    if base:
        return text(git(repo, "merge-base", revision(repo, base), head)).strip(), head
    parents = text(git(repo, "show", "-s", "--format=%P", head)).split()
    parent = (
        parents[0]
        if parents
        else text(
            git(repo, "hash-object", "-t", "tree", "--stdin", input_data=b"")
        ).strip()
    )
    return parent, head


def commits(
    repo: Path, ref: str, limit: int, skip: int = 0, *, bodies=False
) -> list[dict]:
    fields = ["sha", "short", "author", "date", "subject"]
    fmt = "%H%x00%h%x00%an%x00%aI%x00%s"
    if bodies:
        fields.append("body")
        fmt += "%x00%B"
    raw = git(
        repo,
        "log",
        "-z",
        "--format=" + fmt,
        f"--max-count={limit}",
        f"--skip={skip}",
        revision(repo, ref),
        "--",
    )
    values = text(raw).split("\0")[:-1]
    return [
        dict(zip(fields, values[i : i + len(fields)]))
        for i in range(0, len(values), len(fields))
    ]


def history(repo: Path, ref: str | None = None, skip: int = 0) -> dict:
    current = text(git(repo, "branch", "--show-current")).strip() or "HEAD"
    branches = text(
        git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    ).splitlines()
    selected = ref or current
    if not branches and selected in (current, "HEAD"):
        probe = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
            check=False,
            capture_output=True,
        )
        if probe.returncode:
            return {
                "name": repo.name,
                "branch": current,
                "branches": [],
                "commits": [],
                "more": False,
            }
    rows = commits(repo, selected, 51, max(0, skip))
    return {
        "name": repo.name,
        "branch": current,
        "branches": branches,
        "commits": rows[:50],
        "more": len(rows) > 50,
    }


def changed_files(repo: Path, base: str, head: str) -> list[dict]:
    def fields(option: str) -> list[str]:
        return text(git(repo, *DIFF, option, "-z", base, head, "--")).split("\0")[:-1]

    changes = []
    statuses = iter(fields("--name-status"))
    for status in statuses:
        old = next(statuses)
        path = next(statuses) if status[0] in "RC" else old
        changes.append(
            {"path": path, "oldPath": old if path != old else None, "status": status[0]}
        )
    counts = {}
    parts = iter(fields("--numstat"))
    for item in parts:
        plus, minus, path = item.split("\t", 2)
        if not path:
            next(parts)
            path = next(parts)
        counts[path] = (None, None) if plus == "-" else (int(plus), int(minus))
    for change in changes:
        change["added"], change["deleted"] = counts.get(change["path"], (None, None))
    return changes


def patch(repo: Path, base: str, head: str, paths=(), limit: int = PATCH_LIMIT) -> dict:
    # Reading one extra byte distinguishes a complete patch from a capped preview.
    command = [
        "git",
        *GIT_OPTIONS,
        "-C",
        str(repo),
        *DIFF,
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base,
        head,
        "--",
        *paths,
    ]
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as process:
        assert process.stdout
        data = process.stdout.read(limit + 1)
        truncated = len(data) > limit
        if truncated:
            process.kill()
        if process.wait() and not truncated:
            raise ValueError("Git could not produce the requested diff.")
    return {"text": text(data[:limit]), "truncated": truncated}


def github_repo(repo: Path) -> str:
    try:
        remote = text(git(repo, "config", "--get", "remote.origin.url")).strip()
    except ValueError:
        return ""
    match = re.fullmatch(
        rf"(?:https?://(?:[^/@]+@)?github\.com/|(?:ssh://)?git@github\.com[:/])({SLUG})",
        remote,
        re.IGNORECASE,
    )
    return match.group(1).removesuffix(".git") if match else ""


def references(message: str, slug: str) -> dict[str, dict]:
    output = {}
    for match in REFERENCE.finditer(message):
        project = (match["url_repo"] or match["repo"] or slug).lower()
        number = int(match["url_num"] or match["num"])
        key = f"{project}#{number}"
        output[key] = {
            "id": key,
            "repo": project,
            "number": number,
            "label": key if project != slug.lower() else f"#{number}",
        }
    return output


def code_connections(repo: Path, head: str, changes: list[dict]) -> list[dict]:
    """Bounded, exact-revision context for reviews. Test-name matches are labeled as such."""
    sources = [
        f["path"]
        for f in changes
        if f["status"] != "D"
        and Path(f["path"]).suffix
        in {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    ][:24]
    if not sources:
        return []
    entries = {}
    tests = []
    for item in text(git(repo, "ls-tree", "-rlz", head)).split("\0"):
        if not item:
            continue
        header, path = item.split("\t", 1)
        mode, kind, oid, size = header.split()
        if kind != "blob" or mode == "120000":
            continue
        entries[path] = (oid, int(size))
        if re.search(r"(?:^|/)(?:tests/|test_[^/]+$)|\.(?:test|spec)\.", path):
            tests.append(path)
    links = []
    for path in sources:
        if path not in entries:
            continue
        oid, size = entries[path]
        if size <= 160_000:
            source = text(git(repo, "cat-file", "blob", oid))
            for match in IMPORT_RE.finditer(source):
                spec = next((g for g in match.groups() if g), "")
                for candidate in module_to_path_candidates(path, spec):
                    resolved = posixpath.normpath(candidate)
                    if resolved in entries:
                        edge = {
                            "source": path,
                            "target": resolved,
                            "relation": "imports",
                        }
                        if edge not in links:
                            links.append(edge)
                        break
                if len(links) >= 100:
                    return links
        stem = Path(path).stem
        matches = [
            t
            for t in tests
            if t != path
            and Path(t).name.startswith(
                (stem + ".test.", stem + ".spec.", "test_" + stem + ".")
            )
        ]
        links.extend(
            {"source": t, "target": path, "relation": "test name matches"}
            for t in matches[:5]
        )
    return links[:100]


def inspect(repo: Path, head="HEAD", base=None) -> dict:
    base, head = comparison(repo, head, base)
    commit = commits(repo, head, 1, bodies=True)[0]
    files = changed_files(repo, base, head)
    preview = patch(repo, base, head)
    paths = [f["path"] for f in files]
    risks = classify_risks(paths, preview["text"])
    matches = {risk["label"]: [] for risk in risks}
    for path in paths:
        for risk in classify_risks([path], ""):
            matches[risk["label"]].append(path)
    for risk in risks:
        risk["paths"] = matches[risk["label"]]
    slug = github_repo(repo)
    refs = references(commit["body"], slug)
    related = []
    if refs:
        for previous in commits(repo, head, 101, bodies=True)[1:]:
            common = sorted(refs.keys() & references(previous["body"], slug).keys())
            if common:
                related.append(
                    {
                        "sha": previous["sha"],
                        "short": previous["short"],
                        "subject": previous["subject"],
                        "refs": common,
                    }
                )
    return {
        "commit": commit,
        "base": base,
        "head": head,
        "files": files,
        "risks": risks,
        "slug": slug,
        "refs": list(refs.values()),
        "related": related,
        "connections": code_connections(repo, head, files),
        "patchTruncated": preview["truncated"],
    }
