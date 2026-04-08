#!/usr/bin/env bash
# setup_worktrees.sh — create one git worktree per agent.
# Usage: setup_worktrees.sh <target-repo> <agent-name> [agent-name ...]
set -euo pipefail

REPO="${1:?Usage: setup_worktrees.sh <target-repo> [--base <branch>] <agent-name> [agent-name ...]}"
shift
BASE_OVERRIDE=""
if [ "${1:-}" = "--base" ]; then
    BASE_OVERRIDE="$2"; shift 2
fi
[ "$#" -ge 1 ] || { echo "need at least one agent name" >&2; exit 1; }

cd "$REPO"
git rev-parse --is-inside-work-tree >/dev/null

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "[setup] error: repo has no commits yet — make at least one commit before running c3r init" >&2
    echo "[setup]   quick fix: git -c commit.gpgsign=false commit --allow-empty -m init" >&2
    exit 1
fi

if [ -n "$BASE_OVERRIDE" ]; then
    git show-ref --verify --quiet "refs/heads/$BASE_OVERRIDE" || {
        echo "[setup] base branch '$BASE_OVERRIDE' does not exist; create it first" >&2; exit 1;
    }
    BASE="$BASE_OVERRIDE"
else
    BASE="$(git symbolic-ref --short HEAD)"
fi
echo "[setup] basing agent branches off: $BASE"
PARENT="$(dirname "$REPO")"
REPO_NAME="$(basename "$REPO")"

for name in "$@"; do
    branch="agent/$name"
    wt="$PARENT/${REPO_NAME}-${name}"
    if git show-ref --verify --quiet "refs/heads/$branch"; then
        echo "[setup] branch $branch already exists; reusing"
    else
        git branch "$branch" "$BASE"
    fi
    if [ -d "$wt" ]; then
        echo "[setup] worktree $wt already exists; skipping"
    else
        git worktree add "$wt" "$branch"
        echo "[setup] created worktree $wt on $branch"
    fi
done

echo "[setup] done. Worktrees:"
git worktree list
