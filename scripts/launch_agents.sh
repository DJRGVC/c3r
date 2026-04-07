#!/usr/bin/env bash
# launch_agents.sh — tmux session with two Ralph agents + a live log window.
# Usage: launch_agents.sh <target-repo-path> [agent-a] [agent-b]
set -euo pipefail

REPO="${1:?Usage: launch_agents.sh <target-repo> [agent-a] [agent-b]}"
A_NAME="${2:-policy}"
B_NAME="${3:-perception}"
SESSION="${C3R_TMUX_SESSION:-c3r}"

PARENT="$(dirname "$REPO")"
REPO_NAME="$(basename "$REPO")"
A_WT="$PARENT/${REPO_NAME}-${A_NAME}"
B_WT="$PARENT/${REPO_NAME}-${B_NAME}"

for wt in "$A_WT" "$B_WT"; do
    [ -d "$wt" ] || { echo "[launch] missing worktree $wt — run setup_worktrees.sh first" >&2; exit 1; }
done

# Require Discord env (agents will need it for ask_human.py).
: "${DISCORD_BOT_TOKEN:?set DISCORD_BOT_TOKEN}"
: "${DISCORD_CHANNEL_ID:?set DISCORD_CHANNEL_ID}"
: "${DISCORD_USER_ID:?set DISCORD_USER_ID}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[launch] session $SESSION already exists; attach with: tmux attach -t $SESSION" >&2
    exit 0
fi

RALPH_CMD="${C3R_RALPH_CMD:-ralph --monitor}"

tmux new-session  -d -s "$SESSION" -n "$A_NAME"    -c "$A_WT" "$RALPH_CMD"
tmux new-window   -t "$SESSION"    -n "$B_NAME"    -c "$B_WT" "$RALPH_CMD"
tmux new-window   -t "$SESSION"    -n "logs"       -c "$REPO" \
    "tail -F '$A_WT/.ralph/RESEARCH_LOG.md' '$B_WT/.ralph/RESEARCH_LOG.md' 2>/dev/null || bash"

echo "[launch] session '$SESSION' up. Attach: tmux attach -t $SESSION"
