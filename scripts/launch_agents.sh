#!/usr/bin/env bash
# launch_agents.sh — tmux session with one window per agent + a logs window.
#
# Reads agent list from the project's state.json (one window per agent).
# Each window runs bin/agent_loop.sh with the right env.
#
# Usage: launch_agents.sh <target-repo>
set -euo pipefail

REPO="${1:?Usage: launch_agents.sh <target-repo>}"
REPO="$(cd "$REPO" && pwd)"
STATE="$REPO/.c3r/state.json"
[ -f "$STATE" ] || { echo "[launch] missing $STATE — run 'c3r init' first" >&2; exit 1; }

: "${DISCORD_BOT_TOKEN:?set DISCORD_BOT_TOKEN}"
: "${DISCORD_USER_ID:?set DISCORD_USER_ID}"
# Read channel_id from state.json — config.env's DISCORD_CHANNEL_ID only
# holds ONE channel (whichever project was init'd last), so we always
# override per-project from state. This prevents multi-project setups
# from polling the wrong channel.
PROJECT_CHANNEL_ID="$(python3 -c "import json;print(json.load(open('$STATE'))['channel_id'])")"
: "${PROJECT_CHANNEL_ID:?could not read channel_id from $STATE}"

C3R_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export C3R_DIR
export C3R_BIN="$C3R_DIR/bin"

PROJECT_NAME="$(python3 -c "import json;print(json.load(open('$STATE'))['project'])")"
SESSION="c3r-${PROJECT_NAME}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[launch] session '$SESSION' already exists; attach with: tmux attach -t $SESSION" >&2
    exit 0
fi

# Belt-and-suspenders: kill any orphan listener processes for this project
# that might have survived a previous tmux kill-session (e.g. SIGHUP not
# propagating cleanly through the bash subshell). This prevents two listeners
# from polling the same channel and double-acking !c3r commands.
PROJECT_KEY="$(basename "$REPO")"
PID_FILE="/tmp/c3r_listen_${PROJECT_KEY}.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[launch] killing orphan listener for $PROJECT_KEY (pid=$OLD_PID)"
        kill -TERM "$OLD_PID" 2>/dev/null || true
        sleep 1
        kill -KILL "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi
# Also pkill any python listen.py whose argv mentions this state path,
# as a final safety net in case the PID file was lost
pkill -f "python3.*listen\.py" -f "$STATE" 2>/dev/null || true

# Read agents list from state.json → newline-separated "name worktree thread_id"
mapfile -t AGENTS < <(python3 -c "
import json
for a in json.load(open('$STATE'))['agents']:
    print(f\"{a['name']}\t{a['worktree']}\t{a.get('thread_id','')}\")
")
[ "${#AGENTS[@]}" -gt 0 ] || { echo "[launch] no agents in state.json" >&2; exit 1; }

# SECURITY: source the config.env so credentials live in env vars only
# (not on the command line where `ps -ef` could leak them to other users).
CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/c3r/config.env"

first=1
for line in "${AGENTS[@]}"; do
    IFS=$'\t' read -r name worktree thread <<<"$line"
    # Source config.env inside the bash command to load Discord creds without
    # putting them on the visible-to-`ps` command line.
    env_cmd="cd '$worktree' && \
        set -a; . '$CONFIG_FILE'; set +a; \
        export DISCORD_CHANNEL_ID='$PROJECT_CHANNEL_ID' \
        C3R_DIR='$C3R_DIR' C3R_BIN='$C3R_BIN' C3R_STATE='$STATE' \
        C3R_AGENT_NAME='$name' C3R_WORKTREE='$worktree' \
        C3R_AGENT_THREAD_ID='$thread' && \
        '$C3R_BIN/agent_loop.sh'"
    if [ "$first" = 1 ]; then
        tmux new-session -d -s "$SESSION" -n "$name" "bash -lc \"$env_cmd\""
        first=0
    else
        tmux new-window -t "$SESSION" -n "$name" "bash -lc \"$env_cmd\""
    fi
done

# Logs window: tail every agent's RESEARCH_LOG.md
tail_args=""
for line in "${AGENTS[@]}"; do
    IFS=$'\t' read -r _ worktree _ <<<"$line"
    tail_args+="'$worktree/.c3r/RESEARCH_LOG.md' "
done
tmux new-window -t "$SESSION" -n "logs" "bash -lc \"tail -F $tail_args 2>/dev/null || bash\""

echo "[launch] session '$SESSION' up. Attach: tmux attach -t $SESSION"
