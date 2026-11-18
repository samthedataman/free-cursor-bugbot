# Security

Free Cursor Bugbot is local-first by default. It builds a SQLite graph and impact reports on the machine where it runs.

## Sensitive Data

Do not publish generated `.repo-bugbot/` artifacts from private repositories unless you have reviewed them. Impact reports can include file paths, route names, env var names, service names, and code-adjacent metadata.

## Model reviews

The desktop and review CLI use the checker configuration selected by the user. An explicit review sends Git diff text, changed paths and related metadata to each selected provider. Store API keys in the launching process environment. Local Ollama and LM Studio endpoints support offline model reviews. The CLI adapters start in a temporary directory and receive the committed change on standard input.

Review receipts can contain source paths, findings, and model output. They are stored under the user-owned Bugbot data directory. GitHub issue enrichment uses the authenticated GitHub CLI when requested from the inspector.

## Reporting Issues

Report security issues through GitHub's private vulnerability reporting if it is enabled for the repository. Otherwise, open a minimal issue asking for a private disclosure channel.

## Design Principles

- no source upload is required for local mode
- hooks are non-blocking and do not spawn paid agents
- generated graph data is disposable
- public frontend env vars are treated as public
- production config changes are classified as high risk
