# Repo Bugbot

Local-first PR review intelligence for teams that ship in large, messy repositories.

Repo Bugbot turns a pull request into a **blast-radius map**. It does not only read the changed files. It builds a local SQLite graph of the repository, walks the relationships around the diff, classifies production risk, and generates focused review prompts for humans or coding agents.

## The Problem

Most code review tools read a diff and comment on the lines that changed. That misses the bugs that actually break production:

- a backend route changed but the frontend client contract was not updated
- a worker retry path now double-sends an email, SMS, CRM note, or webhook
- a Render env var was declared on the wrong service
- a public `VITE_*` value is treated like a private billing/auth gate
- a new React component exists but is never mounted
- a Twilio, Stripe, Filevine, or outbound campaign write is not idempotent

Repo Bugbot reviews the **system around the change**.

## How It Works

Repo Bugbot has four layers.

1. **Graph Indexer**

   Scans the repo into `.repo-bugbot/graph.sqlite`.

   It indexes:

   - files
   - Python and TypeScript symbols
   - imports and local import edges
   - FastAPI, decorator, and Express-style routes
   - env vars referenced in code
   - Render services and declared env vars from `render.yaml`
   - likely test-to-source relationships

2. **Diff Impact Engine**

   Compares `base...HEAD`, seeds the graph with changed files, and walks nearby nodes to find impacted callers, tests, routes, env vars, services, and public surfaces.

3. **Risk Classifier**

   Detects risky categories such as:

   - billing and provisioning
   - external CRM writes
   - config/env boundary changes
   - worker, queue, retry, and campaign runtime changes
   - route, webhook, auth, and onboarding changes
   - public UI, widget, iframe, and mobile/desktop changes

4. **Review Prompts**

   Generates strict prompts for focused review agents:

   - `security-billing-config`
   - `runtime-data-integrations`
   - `frontend-reachability-ux`

## Quickstart

From the repository you want to review:

```bash
python3 -m pip install git+https://github.com/samthedataman/repo-bugbot.git
```

Build the graph:

```bash
repo-bugbot-index --repo . --db .repo-bugbot/graph.sqlite
```

Generate an impact report against `origin/master`:

```bash
repo-bugbot-impact \
  --repo . \
  --db .repo-bugbot/graph.sqlite \
  --base origin/master \
  --head HEAD \
  --format markdown \
  --out .repo-bugbot/impact.md
```

Open:

```bash
cat .repo-bugbot/impact.md
```

The markdown report includes:

- changed files
- detected risk categories
- top impacted graph nodes
- changed env vars, route strings, and symbols
- focused agent prompts

## Local SQLite Graph

The graph database is local and disposable:

```text
.repo-bugbot/graph.sqlite
```

Example relationship map:

```text
AdminNewsletterPanel.tsx
  imports_file -> adminApi.ts

adminApi.ts
  references_env -> VITE_API_BASE_URL

admin_router.py
  registers_route -> GET /api/v1/admin/newsletter/operations
  references_env -> RENDER_API_KEY

render.yaml
  declares_service -> legalvoice-api
  declares_env -> RENDER_API_KEY
```

When a PR touches `admin_router.py`, Repo Bugbot can point reviewers toward the frontend client, admin panel, Render env config, and tests that are likely affected.

## Git Hook Mode

Repo Bugbot can refresh the graph after checkouts, pulls, and rebases.

Use the provided hook scripts from the repository you want to review:

```bash
git config core.hooksPath /absolute/path/to/repo-bugbot/githooks
```

Disable hooks temporarily:

```bash
REPO_BUGBOT_HOOKS=0 git pull
```

The hooks are intentionally non-blocking. They do not spawn paid agents, mutate code, or fail your Git command. They only refresh:

```text
.repo-bugbot/graph.sqlite
.repo-bugbot/impact.md
.repo-bugbot/impact.json
.repo-bugbot/last-hook.log
```

## Agent Workflow

Recommended review flow:

```bash
repo-bugbot-index --repo . --db .repo-bugbot/graph.sqlite
repo-bugbot-impact --repo . --db .repo-bugbot/graph.sqlite --base origin/master --out .repo-bugbot/impact.md
```

Then give `.repo-bugbot/impact.md` to three reviewers or agents:

1. Security, billing, config
2. Runtime, workers, integrations
3. Frontend reachability and UX

Each reviewer should return only material issues with file and line references.

## SaaS Tier Roadmap

Repo Bugbot is currently local-first private beta software. The hosted SaaS roadmap is:

### Local

For individual developers and private beta testers.

- local SQLite graph
- local impact reports
- local Git hook refresh
- no code leaves your machine
- agent prompt generation

### Pro

For solo builders and small teams.

- GitHub PR comment bot
- saved impact reports per PR
- risk badges on pull requests
- review prompt export for Codex, Claude, Cursor, or internal agents
- configurable base branches

### Team

For engineering teams shipping production systems.

- organization dashboard
- repo risk history
- required-review policies by risk category
- CODEOWNERS-style routing by impacted surface
- Slack alerts for high-risk PRs
- merge-readiness checklist

### Enterprise

For regulated or high-scale teams.

- self-hosted or VPC deployment
- SSO/SAML
- audit logs
- custom risk rules
- internal model routing
- private source retention controls
- compliance exports

## Security Model

Repo Bugbot is designed to be local-first:

- source code stays on the machine where the graph is built
- `.repo-bugbot/graph.sqlite` is a generated local artifact
- generated reports should be treated as internal engineering artifacts
- public frontend env vars are considered public and never trusted as auth
- Render/env changes are treated as production-risk changes

Do not commit `.repo-bugbot/` artifacts unless your team explicitly wants to store reports.

## Current Status

Private beta.

This repo is intentionally private while the framework, docs, and product workflow harden. Before making it public, add a public license, CI, packaged releases, and sanitized example reports.
