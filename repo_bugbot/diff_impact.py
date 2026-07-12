#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


RISK_RULES = [
    ("critical", re.compile(r"(stripe|billing|checkout|subscription|trial|twilio|provision|phone)", re.I), "billing/provisioning"),
    ("critical", re.compile(r"(crm|filevine|smartadvocate|writeback|append|note|timeline)", re.I), "external CRM write"),
    ("high", re.compile(r"(render\.yaml|\.env|VITE_|SECRET|TOKEN|API_KEY|WEBHOOK)", re.I), "config/env boundary"),
    ("high", re.compile(r"(worker|queue|retry|idempot|dispatch|campaign|outbound)", re.I), "worker/campaign runtime"),
    ("high", re.compile(r"(router|route|webhook|callback|auth|onboarding)", re.I), "route/auth/onboarding"),
    ("medium", re.compile(r"(public|landing|widget|iframe|preview|mobile|desktop)", re.I), "public UI/runtime"),
    ("medium", re.compile(r"(test_|tests/|\.test\.|\.spec\.)", re.I), "test surface"),
]

EDGE_WEIGHTS = {
    "imports_file": 8,
    "tests": 8,
    "references_env": 7,
    "declares_env": 7,
    "has_env": 6,
    "registers_route": 6,
    "declares_service": 6,
    "defines": 3,
    "exports": 3,
    "imports": 2,
    "has_tag": 1,
}


def run_git(repo: Path, args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL)


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    raw = run_git(repo, ["diff", "--name-only", f"{base}...{head}"])
    return [line.strip() for line in raw.splitlines() if line.strip()]


def changed_hunks(repo: Path, base: str, head: str) -> str:
    return run_git(repo, ["diff", "--unified=0", f"{base}...{head}"])


def node_by_file(con: sqlite3.Connection, path: str) -> dict[str, Any] | None:
    row = con.execute("SELECT id,type,key,path,name,meta FROM nodes WHERE type='file' AND key=?", (path,)).fetchone()
    if not row:
        return None
    return row_to_node(row)


def row_to_node(row: tuple[Any, ...]) -> dict[str, Any]:
    meta = {}
    try:
        meta = json.loads(row[5] or "{}")
    except Exception:
        meta = {}
    return {"id": int(row[0]), "type": row[1], "key": row[2], "path": row[3], "name": row[4], "meta": meta}


def neighbors(con: sqlite3.Connection, node_id: int) -> list[tuple[dict[str, Any], str, str]]:
    rows = con.execute(
        """
        SELECT n.id,n.type,n.key,n.path,n.name,n.meta,e.type,'out'
        FROM edges e JOIN nodes n ON n.id=e.dst
        WHERE e.src=?
        UNION ALL
        SELECT n.id,n.type,n.key,n.path,n.name,n.meta,e.type,'in'
        FROM edges e JOIN nodes n ON n.id=e.src
        WHERE e.dst=?
        """,
        (node_id, node_id),
    ).fetchall()
    return [(row_to_node(row[:6]), row[6], row[7]) for row in rows]


def classify_risks(changed: list[str], diff_text: str) -> list[dict[str, str]]:
    haystack = "\n".join(changed) + "\n" + diff_text[:200_000]
    seen = set()
    risks: list[dict[str, str]] = []
    for severity, regex, label in RISK_RULES:
        if regex.search(haystack) and label not in seen:
            seen.add(label)
            risks.append({"severity": severity, "label": label})
    return risks


def extract_changed_tokens(diff_text: str) -> dict[str, list[str]]:
    env = sorted(set(re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", diff_text)))
    names = sorted(set(re.findall(r"\b(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)", diff_text)))
    routes = sorted(set(re.findall(r"['\"](/[A-Za-z0-9_./{}:-]+)['\"]", diff_text)))
    return {
        "env": [item for item in env if len(item) >= 4][:80],
        "symbols": names[:80],
        "routes": routes[:80],
    }


def impact(con: sqlite3.Connection, changed: list[str], *, depth: int = 2) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    seeds: list[dict[str, Any]] = []
    missing: list[str] = []
    for path in changed:
        node = node_by_file(con, path)
        if node:
            seeds.append(node)
        else:
            missing.append(path)

    scores: Counter[int] = Counter()
    reasons: dict[int, list[str]] = defaultdict(list)
    queue: deque[tuple[dict[str, Any], int, str]] = deque((node, 0, "changed_file") for node in seeds)
    visited: set[tuple[int, int]] = set()

    while queue:
        node, dist, reason = queue.popleft()
        key = (node["id"], dist)
        if key in visited:
            continue
        visited.add(key)
        base_score = max(1, (depth + 1 - dist) * 10)
        scores[node["id"]] += base_score
        if len(reasons[node["id"]]) < 6:
            reasons[node["id"]].append(reason)
        if dist >= depth:
            continue
        for nxt, edge_type, direction in neighbors(con, node["id"]):
            edge_score = EDGE_WEIGHTS.get(edge_type, 1)
            scores[nxt["id"]] += edge_score
            if len(reasons[nxt["id"]]) < 6:
                reasons[nxt["id"]].append(f"{direction}:{edge_type}:{node['key']}")
            queue.append((nxt, dist + 1, f"{direction}:{edge_type}:{node['key']}"))

    if not scores:
        return [], {"missing_changed_files": missing}

    placeholders = ",".join("?" for _ in scores)
    rows = con.execute(
        f"SELECT id,type,key,path,name,meta FROM nodes WHERE id IN ({placeholders})",
        tuple(scores.keys()),
    ).fetchall()
    nodes = [row_to_node(row) for row in rows]
    nodes.sort(key=lambda node: (-scores[node["id"]], node["type"], node["key"]))
    results = []
    for node in nodes[:250]:
        results.append(
            {
                **node,
                "score": int(scores[node["id"]]),
                "reasons": reasons[node["id"]],
            }
        )
    return results, {"missing_changed_files": missing}


def build_agent_prompts(changed: list[str], risks: list[dict[str, str]], impacted: list[dict[str, Any]]) -> list[dict[str, str]]:
    risk_labels = ", ".join(f"{item['severity']}:{item['label']}" for item in risks) or "general code review"
    impacted_files = [node["key"] for node in impacted if node["type"] == "file"][:40]
    impacted_env = [node["key"] for node in impacted if node["type"] == "env"][:30]
    impacted_routes = [node["key"] for node in impacted if node["type"] == "route"][:30]
    common = (
        "Use git diff against the base and the repo-bugbot impact report. "
        "Report only material bugs with file/line references. Ignore style-only issues."
    )
    prompts = [
        {
            "surface": "security-billing-config",
            "prompt": (
                f"{common}\nFocus: public env exposure, auth/billing bypass, Stripe/Twilio provisioning, "
                f"webhook trust, tenant isolation, secrets, render.yaml/env changes.\nRisks: {risk_labels}\n"
                f"Changed files: {changed[:60]}\nImpacted env: {impacted_env}\nImpacted routes: {impacted_routes}"
            ),
        },
        {
            "surface": "runtime-data-integrations",
            "prompt": (
                f"{common}\nFocus: workers, idempotency, duplicate sends/provisioning, CRM writes, storage, "
                f"retry behavior, data loss, post-call/outbound side effects.\nRisks: {risk_labels}\n"
                f"Changed files: {changed[:60]}\nImpacted files: {impacted_files}"
            ),
        },
        {
            "surface": "frontend-reachability-ux",
            "prompt": (
                f"{common}\nFocus: whether new components are actually imported/mounted, route reachability, "
                f"client/server API contract, iframe/fallback handling, mobile/desktop breakage.\nRisks: {risk_labels}\n"
                f"Changed files: {changed[:60]}\nImpacted files: {impacted_files}"
            ),
        },
    ]
    return prompts


def write_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Repo Bugbot Impact Report",
        "",
        f"- Base: `{report['base']}`",
        f"- Head: `{report['head']}`",
        f"- Changed files: {len(report['changed_files'])}",
        "",
        "## Risks",
    ]
    if report["risks"]:
        for risk in report["risks"]:
            lines.append(f"- **{risk['severity']}**: {risk['label']}")
    else:
        lines.append("- No named high-risk pattern detected.")
    lines.extend(["", "## Changed Files"])
    for path in report["changed_files"][:120]:
        lines.append(f"- `{path}`")
    lines.extend(["", "## Top Impacted Nodes"])
    for node in report["impacted"][:80]:
        path = f" `{node['path']}`" if node.get("path") else ""
        reasons = "; ".join(node.get("reasons") or [])[:240]
        lines.append(f"- {node['score']:>3} `{node['type']}:{node['key']}`{path} - {reasons}")
    lines.extend(["", "## Changed Tokens"])
    for kind, values in report["changed_tokens"].items():
        lines.append(f"- {kind}: {', '.join(f'`{v}`' for v in values[:40]) or '-'}")
    lines.extend(["", "## Agent Prompts"])
    for prompt in report["agent_prompts"]:
        lines.append(f"### {prompt['surface']}")
        lines.append("```text")
        lines.append(prompt["prompt"])
        lines.append("```")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute PR blast radius from a repo-bugbot graph DB.")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--db", default=".repo-bugbot/graph.sqlite", help="SQLite graph DB path")
    parser.add_argument("--base", default="origin/master", help="Base ref")
    parser.add_argument("--head", default="HEAD", help="Head ref")
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--out", default="", help="Output file. JSON sidecar is always written next to markdown when possible.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    db = Path(args.db)
    if not db.is_absolute():
        db = repo / db
    if not db.exists():
        raise SystemExit(f"Graph DB not found: {db}. Run index_repo_graph.py first.")

    changed = changed_files(repo, args.base, args.head)
    diff_text = changed_hunks(repo, args.base, args.head)
    con = sqlite3.connect(db)
    impacted, meta = impact(con, changed, depth=args.depth)
    con.close()
    risks = classify_risks(changed, diff_text)
    changed_tokens = extract_changed_tokens(diff_text)
    report = {
        "repo": str(repo),
        "db": str(db),
        "base": args.base,
        "head": args.head,
        "changed_files": changed,
        "changed_tokens": changed_tokens,
        "risks": risks,
        "impacted": impacted,
        "meta": meta,
        "agent_prompts": build_agent_prompts(changed, risks, impacted),
    }

    out = Path(args.out) if args.out else repo / ".repo-bugbot" / "impact.md"
    if not out.is_absolute():
        out = repo / out
    out.parent.mkdir(parents=True, exist_ok=True)
    json_out = out.with_suffix(".json")
    json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.format == "json":
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    else:
        out.write_text(write_markdown(report), encoding="utf-8")
    print(json.dumps({"out": str(out), "json": str(json_out), "changed_files": len(changed), "impacted": len(impacted)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
