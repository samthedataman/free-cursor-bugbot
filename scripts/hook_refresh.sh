#!/usr/bin/env bash
set -u

repo="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo" || exit 0

if [ "${REPO_BUGBOT_HOOKS:-1}" = "0" ]; then
  exit 0
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tool_root="$(cd "$script_dir/.." && pwd)"
python_bin="${REPO_BUGBOT_PYTHON:-python3}"

if ! command -v "$python_bin" >/dev/null 2>&1; then
  exit 0
fi

mkdir -p "$repo/.repo-bugbot"

base="${REPO_BUGBOT_BASE:-origin/master}"
if ! git rev-parse --verify "$base" >/dev/null 2>&1; then
  base="HEAD~1"
fi

branch="$(git branch --show-current 2>/dev/null || true)"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

{
  echo "repo-bugbot hook refresh"
  echo "time=$timestamp"
  echo "branch=$branch"
  echo "base=$base"
} > "$repo/.repo-bugbot/last-hook.log"

PYTHONPATH="$tool_root:${PYTHONPATH:-}" "$python_bin" -m repo_bugbot.index_repo_graph --repo "$repo" --db "$repo/.repo-bugbot/graph.sqlite" --quiet >> "$repo/.repo-bugbot/last-hook.log" 2>&1 || exit 0
PYTHONPATH="$tool_root:${PYTHONPATH:-}" "$python_bin" -m repo_bugbot.diff_impact --repo "$repo" --db "$repo/.repo-bugbot/graph.sqlite" --base "$base" --head HEAD --format markdown --out "$repo/.repo-bugbot/impact.md" >> "$repo/.repo-bugbot/last-hook.log" 2>&1 || exit 0

echo "repo-bugbot: refreshed .repo-bugbot/impact.md for $branch" >&2
exit 0
