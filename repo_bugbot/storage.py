"""User-owned configuration and immutable review receipts outside inspected repos."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .checkers import initial_config


def home() -> Path:
    return Path(os.getenv("REPO_BUGBOT_HOME") or Path.home() / ".repo-bugbot")


def config(path=None) -> dict:
    file = Path(path) if path else home() / "checkers.json"
    if not path and not file.exists():
        return initial_config()
    return json.loads(file.read_text(encoding="utf-8"))


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, encoding="utf-8", prefix=".writing-", delete=False
    ) as handle:
        tmp = Path(handle.name)
        try:
            json.dump(data, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def run_dir(repo: Path, base: str, head: str) -> Path:
    identity = hashlib.sha256(os.fsencode(repo.resolve())).hexdigest()[:32]
    return home() / "runs" / identity / head / base


def runs(repo, base, head):
    reports = []
    for path in sorted(run_dir(repo, base, head).glob("*.json"), reverse=True):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return reports
