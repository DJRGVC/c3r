#!/usr/bin/env bash
# agent_loop.sh — the c3r replacement for Ralph's --monitor loop.
#
# Runs a single agent continuously: reads .c3r/PROMPT.md, invokes
# `claude -p` with JSON output, parses token usage for the context %,
# calls heartbeat, honors pause flags, and implements a simple circuit
# breaker.
#
# Expected env (exported by launch_agents.sh):
#   C3R_DIR             absolute path to c3r repo (for $C3R_DIR/bin)
#   C3R_BIN             absolute path to $C3R_DIR/bin (also for agents)
#   C3R_STATE           absolute path to the project's state.json
#   C3R_AGENT_NAME      agent name (matches state.json entry)
#   C3R_WORKTREE        absolute path to this agent's git worktree
#   DISCORD_*           all three Discord vars
#
# Pause semantics: `c3r pause` touches <worktree>/.c3r/PAUSED. We check
# the flag between iterations; the CURRENT iteration finishes first
# (non-destructive — no SIGSTOP, no killed training jobs).
set -u

: "${C3R_DIR:?C3R_DIR unset}"
: "${C3R_BIN:?C3R_BIN unset}"
: "${C3R_STATE:?C3R_STATE unset}"
: "${C3R_AGENT_NAME:?C3R_AGENT_NAME unset}"
: "${C3R_WORKTREE:?C3R_WORKTREE unset}"

cd "$C3R_WORKTREE"
CONF="$C3R_WORKTREE/.c3r/agent.conf"
PAUSE_FLAG="$C3R_WORKTREE/.c3r/PAUSED"
PROMPT="$C3R_WORKTREE/.c3r/PROMPT.md"
ENV_FILE="$C3R_WORKTREE/.c3r/env.sh"
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"
# Project-specific environment activation (venvs, CUDA, conda, etc).
# Sourced BEFORE the agent.conf so agent.conf can override if needed.
# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

AGENT_MODEL="${AGENT_MODEL:-claude-sonnet-4-6}"
ITERATION_COOLDOWN_SEC="${ITERATION_COOLDOWN_SEC:-20}"
MAX_CONSECUTIVE_FAILURES="${MAX_CONSECUTIVE_FAILURES:-5}"
ITERATION_TIMEOUT_SEC="${ITERATION_TIMEOUT_SEC:-3600}"  # 1h hard cap per iter
CONTEXT_WINDOW=200000  # Claude 4.6 default

fail_streak=0
iter_id=0

hb() { "$C3R_BIN/heartbeat.py" --state "$C3R_STATE" --agent "$C3R_AGENT_NAME" "$@"; }

hb --status idle

while :; do
    # --- pause check ---
    while [ -f "$PAUSE_FLAG" ]; do
        hb --status paused
        sleep 15
    done

    # --- refresh the SIBLINGS.md snapshot so the agent has fresh cross-branch
    # visibility at the top of every iteration
    "$C3R_BIN/siblings_snapshot.py" "$C3R_STATE" "$C3R_AGENT_NAME" 2>/dev/null || true

    # --- circuit breaker ---
    if [ "$fail_streak" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
        echo "[agent_loop] circuit breaker tripped after $fail_streak failures; pausing" >&2
        "$C3R_BIN/notify.py" --mention \
            "🔴 **$C3R_AGENT_NAME** circuit breaker tripped ($fail_streak failures). Paused. Use \`c3r resume\` after fixing." || true
        touch "$PAUSE_FLAG"
        fail_streak=0
        continue
    fi

    iter_id=$((iter_id + 1))
    hb --status running
    tmp_out="$(mktemp /tmp/c3r_iter.XXXXXX.json)"
    trap 'rm -f "$tmp_out"' EXIT

    # --- invoke claude code headless ---
    # `--output-format json` returns a JSON envelope including usage counts.
    # --dangerously-skip-permissions is REQUIRED for autonomous loops: without
    # it, `claude -p` runs in restricted mode and refuses Edit/Write/Bash, so
    # the agent would read files, reason, and exit without doing any work.
    if claude -p --output-format json --model "$AGENT_MODEL" \
            --dangerously-skip-permissions < "$PROMPT" > "$tmp_out" 2>&1; then
        # parse usage (best effort; missing keys → 0)
        usage_in=$(python3 -c "import json,sys;d=json.load(open('$tmp_out'));print(d.get('usage',{}).get('input_tokens',0))" 2>/dev/null || echo 0)
        usage_out=$(python3 -c "import json,sys;d=json.load(open('$tmp_out'));print(d.get('usage',{}).get('output_tokens',0))" 2>/dev/null || echo 0)
        total=$((usage_in + usage_out))
        pct=$(( total * 100 / CONTEXT_WINDOW ))
        [ "$pct" -gt 100 ] && pct=100
        hb --status idle --inc-iter --context-pct "$pct"
        fail_streak=0
    else
        echo "[agent_loop] claude call failed on iter $iter_id" >&2
        tail -20 "$tmp_out" >&2 || true
        hb --status error --fail
        fail_streak=$((fail_streak + 1))
    fi

    rm -f "$tmp_out"
    trap - EXIT
    sleep "$ITERATION_COOLDOWN_SEC"
done
