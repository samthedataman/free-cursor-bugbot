---
name: repo-bugbot
description: Free local Cursor-style Bugbot workflow for Codex and Claude Code. Use when auditing pull requests, checking merge risk, computing blast radius, or asking agents to review code changes with repository relationship context.
---

# Free Cursor Bugbot

## Goal

Run a free local Cursor-style Bugbot review before merging PRs. The workflow combines deterministic repository graph indexing with Codex, Claude Code, or high-effort agent review so reviewers inspect not just changed files, but also likely affected callers, routes, tests, configs, workers, prompts, and public client surfaces.

Free Cursor Bugbot is independent and not affiliated with Cursor. The point is to give Codex and Claude Code the missing blast-radius context that a raw diff does not provide.

## Workflow

1. Refresh the target PR locally in an isolated worktree.
2. Build or refresh the local graph DB:

```bash
repo-bugbot-index --repo . --db .repo-bugbot/graph.sqlite
```

3. Compute diff blast radius against the target base:

```bash
repo-bugbot-impact --repo . --db .repo-bugbot/graph.sqlite --base origin/master --format markdown --out .repo-bugbot/impact.md
```

4. Read `.repo-bugbot/impact.md` and use it to spawn focused review agents.
5. Assign agents by risk surface:
   - security/billing/config
   - runtime/data/integrations
   - frontend reachability/UX
6. Merge only after material findings are fixed or explicitly accepted and the repo's production gate passes.

## Codex / Claude Code Prompt

```text
Use .repo-bugbot/impact.md and git diff origin/master...HEAD.
Review this PR like a strict Bugbot pass for Codex or Claude Code.
Return only material findings with file and line references.
Prioritize security, billing, worker retries, CRM writes, route/env mismatches,
unreachable UI, and missing tests for risky behavior.
Do not report style-only issues.
```

## Review Prompt Template

```text
Audit this PR like a strict Bugbot/code-review pass.

Read:
- git diff <base>...HEAD
- .repo-bugbot/impact.md

Focus on material bugs only:
- security/privacy/billing bypasses
- untrusted client-side gates
- duplicate external provisioning or writes
- missing idempotency
- unreachable code or unmounted components
- broken API client/server contracts
- route/env/config mismatch
- worker/retry/concurrency regressions
- data loss, wrong tenant/account, or cross-tenant leakage
- test gaps for risky behavior

Return findings ordered by severity with file path and line number.
Do not report style-only issues or unrelated warnings.
Verdict: mergeable / needs fixes / blocked.
```
