#!/usr/bin/env bash
# setup_worktrees.sh — create two git worktrees for concurrent research agents.
# Usage: setup_worktrees.sh <target-repo-path> [agent-a] [agent-b]
set -euo pipefail

REPO="${1:?Usage: setup_worktrees.sh <target-repo> [agent-a-name] [agent-b-name]}"
A_NAME="${2:-policy}"
B_NAME="${3:-perception}"

cd "$REPO"
git rev-parse --is-inside-work-tree >/dev/null

BASE="$(git symbolic-ref --short HEAD)"
PARENT="$(dirname "$REPO")"
REPO_NAME="$(basename "$REPO")"

for name in "$A_NAME" "$B_NAME"; do
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
