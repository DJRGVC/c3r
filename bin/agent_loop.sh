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
# Per-iteration wall-clock cap. Default 5400 (90 min).
# Agents are told about this in PROMPT.md and are expected to save
# checkpoints frequently during long training so a timeout doesn't waste
# the run — the next iteration resumes from the latest checkpoint.
# Override per-agent in agent.conf; set to empty string to disable.
ITERATION_TIMEOUT_SEC="${ITERATION_TIMEOUT_SEC-5400}"
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

    # --- invoke claude code headless in its own process group ---
    # `setsid` puts claude in a new session/process group so we can
    # SIGTERM/SIGKILL the ENTIRE subprocess tree on timeout — including
    # grandchildren like Isaac Sim, Omniverse, pytorch processes, etc.
    # Without this, a hung GPU subprocess becomes an orphan holding memory
    # and cascading OOMs into subsequent iterations.
    # --dangerously-skip-permissions is REQUIRED for autonomous loops.
    setsid bash -c "claude -p --output-format json --model '$AGENT_MODEL' --dangerously-skip-permissions < '$PROMPT' > '$tmp_out' 2>&1" &
    iter_pid=$!
    watchdog_pid=""
    if [ -n "$ITERATION_TIMEOUT_SEC" ]; then
        (
            sleep "$ITERATION_TIMEOUT_SEC"
            if kill -0 "$iter_pid" 2>/dev/null; then
                echo "[agent_loop] timeout after ${ITERATION_TIMEOUT_SEC}s — SIGTERM process group $iter_pid" >&2
                # Negative pid = entire process group
                kill -TERM -"$iter_pid" 2>/dev/null || true
                sleep 30
                if kill -0 "$iter_pid" 2>/dev/null; then
                    echo "[agent_loop] process group still alive after SIGTERM — SIGKILL" >&2
                    kill -KILL -"$iter_pid" 2>/dev/null || true
                fi
            fi
        ) &
        watchdog_pid=$!
    fi
    if wait "$iter_pid" 2>/dev/null; then iter_ok=1; else iter_ok=0; fi
    [ -n "$watchdog_pid" ] && kill "$watchdog_pid" 2>/dev/null && wait "$watchdog_pid" 2>/dev/null || true

    if [ "$iter_ok" = 1 ]; then
        # Context % = input_tokens / 200k. Input tokens represent what was
        # LOADED into the window (system prompt + read files + tool results).
        # Output tokens don't count toward in-turn context pressure; they only
        # matter on the next turn, and each iteration is a fresh turn.
        usage_in=$(python3 -c "import json,sys;d=json.load(open('$tmp_out'));print(d.get('usage',{}).get('input_tokens',0))" 2>/dev/null || echo 0)
        pct=$(( usage_in * 100 / CONTEXT_WINDOW ))
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
