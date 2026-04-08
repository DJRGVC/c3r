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
# 0 or empty = unlimited. Sub-agents default to 20 (set by c3r spawn).
MAX_ITERATIONS="${MAX_ITERATIONS:-0}"
# Per-iteration wall-clock cap. Default 5400 (90 min).
ITERATION_TIMEOUT_SEC="${ITERATION_TIMEOUT_SEC-5400}"
# Context window size in tokens. Claude Opus/Sonnet 4.6 both have 1M
# context generally available (as of 2026-03-13) at standard pricing.
# Haiku 4.5 is still 200k. Auto-detect from model name if unset.
if [ -z "${CONTEXT_WINDOW:-}" ]; then
    case "$AGENT_MODEL" in
        *opus-4-6*|*sonnet-4-6*) CONTEXT_WINDOW=1000000 ;;
        *haiku*)                  CONTEXT_WINDOW=200000  ;;
        *)                        CONTEXT_WINDOW=200000  ;;
    esac
fi

fail_streak=0
iter_id=0

hb() { "$C3R_BIN/heartbeat.py" --state "$C3R_STATE" --agent "$C3R_AGENT_NAME" "$@"; }

hb --status idle

QUOTA_PAUSE_FLAG="$C3R_WORKTREE/.c3r/PAUSED_QUOTA"

while :; do
    # --- pause check (manual or quota-driven) ---
    while [ -f "$PAUSE_FLAG" ]; do
        hb --status paused
        sleep 15
    done
    while [ -f "$QUOTA_PAUSE_FLAG" ]; do
        resume_ts=$(head -1 "$QUOTA_PAUSE_FLAG" 2>/dev/null || echo 0)
        now=$(date +%s)
        if [ "$now" -ge "$resume_ts" ] 2>/dev/null; then
            echo "[agent_loop] quota pause expired; resuming $C3R_AGENT_NAME" >&2
            "$C3R_BIN/notify.py" --thread "${C3R_AGENT_THREAD_ID:-}" \
                "▶ Auto-resumed after quota pause." 2>/dev/null || true
            rm -f "$QUOTA_PAUSE_FLAG"
            break
        fi
        hb --status paused
        sleep 60
    done

    # --- refresh the SIBLINGS.md snapshot so the agent has fresh cross-branch
    # visibility at the top of every iteration
    "$C3R_BIN/siblings_snapshot.py" "$C3R_STATE" "$C3R_AGENT_NAME" 2>/dev/null || true

    # --- iteration budget self-kill (sub-agents) ---
    if [ "${MAX_ITERATIONS:-0}" -gt 0 ] 2>/dev/null && [ "$iter_id" -ge "$MAX_ITERATIONS" ]; then
        echo "[agent_loop] iteration budget reached ($iter_id/$MAX_ITERATIONS); self-killing $C3R_AGENT_NAME" >&2
        "$C3R_BIN/notify.py" --thread "${C3R_AGENT_THREAD_ID:-}" \
            "🛑 Reached my iteration budget ($MAX_ITERATIONS). Self-killing." 2>/dev/null || true
        # Defer to c3r kill so the cleanup logic runs (status, thread, board)
        "$C3R_BIN/../c3r" kill "$C3R_AGENT_NAME" 2>&1 || true
        # The kill should tear down the tmux window we're in; if not, exit.
        exit 0
    fi

    # --- circuit breaker ---
    if [ "$fail_streak" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
        echo "[agent_loop] circuit breaker tripped after $fail_streak failures; pausing" >&2
        "$C3R_BIN/notify.py" --mention \
            "🔴 **$C3R_AGENT_NAME** circuit breaker tripped ($fail_streak failures). Paused. Use \`c3r resume\` after fixing." || true
        touch "$PAUSE_FLAG"
        fail_streak=0
        # Reset state.json fail_streak too so the dashboard shows 0/5 not 5/5
        hb --reset-fails
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
    # --disallowedTools Task blocks Claude Code's built-in Task tool, which
    # would otherwise let the agent spawn an in-context sub-agent that c3r
    # has no visibility into (no worktree, no thread, no max_agents budget).
    # Sub-agent spawning MUST go through `$C3R_BIN/c3r spawn` so it's tracked.
    setsid bash -c "claude -p --output-format json --model '$AGENT_MODEL' --dangerously-skip-permissions --disallowedTools Task < '$PROMPT' > '$tmp_out' 2>&1" &
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
        # Context % must include CACHED tokens. Claude Code uses prompt
        # caching heavily — usage.input_tokens is only the DELTA on a cache
        # hit (typically <100 tokens), while the actual in-window context
        # lives in cache_read_input_tokens. Total in-window usage =
        # input + cache_read + cache_creation. Otherwise context % is always 0%.
        ctx_total=$(python3 -c "
import json
d = json.load(open('$tmp_out'))
u = d.get('usage', {})
print(u.get('input_tokens',0) + u.get('cache_read_input_tokens',0) + u.get('cache_creation_input_tokens',0))
" 2>/dev/null || echo 0)
        pct=$(python3 -c "
total, window = $ctx_total, $CONTEXT_WINDOW
print(min(round(total * 100 / window) if window else 0, 100))
" 2>/dev/null || echo 0)
        hb --status idle --inc-iter --context-pct "$pct"
        fail_streak=0

        # Auto-trigger compaction at high context by injecting a directive
        # into INBOX. The agent reads INBOX at the top of every iter and
        # acts on the directive before any other work. Idempotent: skips
        # if a directive is already pending. NO Discord notification here
        # — heartbeat.py already fires the user-facing alert at the same
        # threshold and we don't want double-pings.
        if [ "$pct" -ge 75 ] 2>/dev/null && ! grep -q "AUTO-COMPACT REQUIRED" "$C3R_WORKTREE/.c3r/INBOX.md" 2>/dev/null; then
            python3 - "$C3R_WORKTREE/.c3r/INBOX.md" "$pct" "$C3R_AGENT_NAME" <<'PY'
import sys, pathlib
from datetime import datetime, timezone
inbox_path, pct, agent = sys.argv[1:]
inbox = pathlib.Path(inbox_path)
inbox.parent.mkdir(parents=True, exist_ok=True)
ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
if not inbox.exists() or "<!-- empty -->" in inbox.read_text():
    inbox.write_text("# INBOX\n")
with inbox.open("a") as f:
    f.write(f"\n---\n[{ts}] system → {agent}\nMSG: 🚨 AUTO-COMPACT REQUIRED — your last iteration's context was at {pct}%. Your NEXT iteration MUST be a dedicated compaction iteration per PROMPT rule 6: read RESEARCH_LOG.md, summarize old entries into a Compacted Summary block, move verbatim entries to RESEARCH_LOG_ARCHIVE.md, prune fix_plan.md, commit. Do NOT do anything else this iteration. After compaction, normal work resumes the iteration after.\n")
print(f"[agent_loop] injected auto-compact directive into {inbox_path}", file=sys.stderr)
PY
        fi
    else
        echo "[agent_loop] claude call failed on iter $iter_id" >&2
        tail -20 "$tmp_out" >&2 || true
        # Quota detection: Claude Code returns specific error messages when
        # the rate limit or weekly cap is hit. If we see one, set the
        # quota-pause flag with a reset hint and skip incrementing fail_streak
        # (the failure isn't the agent's fault).
        if grep -qiE 'rate.?limit|quota.?exceeded|weekly.?(opus|limit)|usage.?limit|try.?again.?in|too.?many.?requests' "$tmp_out" 2>/dev/null; then
            reset_hint=$(grep -oiE 'reset[s]?\s+(at|in)\s+[^"]{1,50}|try\s+again\s+in\s+[^"]{1,50}|in\s+[0-9]+\s+(hours|minutes|h|m)' "$tmp_out" 2>/dev/null | head -1 || true)
            echo "[agent_loop] quota error detected — quota-pausing $C3R_AGENT_NAME" >&2
            echo "[agent_loop] reset hint: ${reset_hint:-(none parsed; will retry hourly)}" >&2
            # Compute resume timestamp: parse hint or default to now+1h
            python3 - "$C3R_WORKTREE/.c3r/PAUSED_QUOTA" "$reset_hint" <<'PY'
import sys, re, time, os
flag, hint = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
resume_ts = time.time() + 3600  # default: 1h
if hint:
    m = re.search(r'(\d+)\s*(hour|hr|h|minute|min|m)', hint, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith(('h','hr')):
            resume_ts = time.time() + n * 3600
        else:
            resume_ts = time.time() + n * 60
with open(flag, "w") as f:
    f.write(f"{resume_ts:.0f}\n{hint}\n")
PY
            "$C3R_BIN/notify.py" --mention \
                "⏸ **$C3R_AGENT_NAME** auto-paused on quota error. Will retry around $(date -d "@$(head -1 "$C3R_WORKTREE/.c3r/PAUSED_QUOTA")" 2>/dev/null || echo 'in ~1h')." || true
            hb --status paused
            # Don't increment fail_streak — quota errors aren't the agent's fault
        else
            hb --status error --fail
            fail_streak=$((fail_streak + 1))
        fi
    fi

    rm -f "$tmp_out"
    trap - EXIT
    sleep "$ITERATION_COOLDOWN_SEC"
done
