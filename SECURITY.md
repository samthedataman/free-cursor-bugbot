# Security

Repo Bugbot is local-first by default. It builds a SQLite graph and impact reports on the machine where it runs.

## Sensitive Data

Do not publish generated `.repo-bugbot/` artifacts from private repositories unless you have reviewed them. Impact reports can include file paths, route names, env var names, service names, and code-adjacent metadata.

## Reporting Issues

While this project is private beta, report security issues directly to the repository owner.

## Design Principles

- no source upload is required for local mode
- hooks are non-blocking and do not spawn paid agents
- generated graph data is disposable
- public frontend env vars are treated as public
- production config changes are classified as high risk
