"""Small JSON interface shared by the packaged and source desktop app."""

from __future__ import annotations

import json
import re
import subprocess

from . import checkers, review, revisions, storage


def issue_details(slug, number):
    if (
        not isinstance(slug, str)
        or not re.fullmatch(revisions.SLUG, slug)
        or type(number) is not int
        or number < 1
    ):
        raise ValueError("Choose a GitHub issue or pull request reference.")
    try:
        data = subprocess.run(
            ["gh", "api", "--hostname", "github.com", f"repos/{slug}/issues/{number}"],
            check=False,
            capture_output=True,
            timeout=25,
        )
    except FileNotFoundError:
        raise ValueError("Install GitHub CLI to load issue details.") from None
    if data.returncode:
        raise ValueError(
            "GitHub could not return this reference. Check gh login and repository access."
        )
    issue = json.loads(data.stdout)
    refs = revisions.references(issue.get("body") or "", slug)
    refs.pop(f"{slug.lower()}#{number}", None)
    return {
        "title": issue["title"],
        "state": issue["state"],
        "kind": "Pull request" if "pull_request" in issue else "Issue",
        "refs": list(refs.values())[:20],
    }


def dispatch(command, args):
    if command == "settings":
        return {
            "checkers": storage.config()["checkers"],
            "providers": {
                name: {"label": info[0], **checkers.defaults(name)}
                for name, info in checkers.PROVIDERS.items()
            },
        }
    if command == "saveSettings":
        rows = checkers.validate_config(args)
        storage.save(storage.home() / "checkers.json", {"checkers": rows})
        return rows
    if command == "issue":
        return issue_details(args.get("repo"), args.get("number"))
    repo = revisions.root(args["directory"])
    if command == "history":
        return revisions.history(repo, args.get("branch"), int(args.get("skip", 0)))
    head = args.get("head") or "HEAD"
    if command == "inspect":
        data = revisions.inspect(repo, head)
        data["runs"] = storage.runs(repo, data["base"], data["head"])
        return data
    if command == "diff":
        base, head = revisions.comparison(repo, head, None)
        paths = args.get("paths")
        if (
            not isinstance(paths, list)
            or not 1 <= len(paths) <= 2
            or any(not isinstance(p, str) or not p for p in paths)
        ):
            raise ValueError("Choose a changed file.")
        return revisions.patch(repo, base, head, paths)
    if command == "run":
        return review.run(repo, head, None, storage.config())
    raise ValueError("Unknown desktop operation.")
