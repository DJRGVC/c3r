#!/usr/bin/env python3
"""
heartbeat.py — called by agent_loop.sh after each iteration.

Updates the project state.json for one agent (status, iter counter, context %),
re-renders the status board in place, and fires context-threshold alerts to the
agent's Discord thread if crossed upward since last heartbeat.

Usage:
  heartbeat.py --state STATE_JSON --agent NAME \
               [--status idle|running|error|stopped|paused] \
               [--inc-iter] [--context-pct N] [--fail]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone

C3R_BIN = os.path.dirname(os.path.realpath(__file__))

def load(path):
    with open(path) as f: return json.load(f)

def save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(state, f, indent=2)
    os.replace(tmp, path)

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--status")
    p.add_argument("--inc-iter", action="store_true")
    p.add_argument("--context-pct", type=int)
    p.add_argument("--fail", action="store_true")
    p.add_argument("--reset-fails", action="store_true",
                   help="Force fail_streak to 0 (used after circuit breaker trips)")
    p.add_argument("--cost-usd", type=float, default=None,
                   help="Add this iteration's cost in USD to the rolling usage file")
    p.add_argument("--model", default=None,
                   help="Model name for cost attribution (used with --cost-usd)")
    args = p.parse_args()

    state = load(args.state)
    agent = next((a for a in state["agents"] if a["name"] == args.agent), None)
    if not agent:
        print(f"[heartbeat] no such agent: {args.agent}", file=sys.stderr); return 1

    prev_pct = agent.get("last_context_pct", 0)
    if args.status: agent["status"] = args.status
    if args.inc_iter:
        agent["last_iter"] = agent.get("last_iter", 0) + 1
        agent["last_iter_ts"] = datetime.now(timezone.utc).isoformat()
    if args.context_pct is not None:
        agent["last_context_pct"] = args.context_pct
    if args.reset_fails:
        agent["fail_streak"] = 0
    elif args.fail:
        agent["fail_streak"] = agent.get("fail_streak", 0) + 1
    elif args.status == "idle":
        agent["fail_streak"] = 0
    save(args.state, state)

    # Cost / usage tracking → ~/.config/c3r/usage.json keyed by ISO week
    if args.cost_usd is not None and args.cost_usd > 0:
        from datetime import date
        usage_path = os.path.expanduser("~/.config/c3r/usage.json")
        os.makedirs(os.path.dirname(usage_path), exist_ok=True)
        try:
            usage = json.load(open(usage_path)) if os.path.exists(usage_path) else {}
        except Exception:
            usage = {}
        iso_year, iso_week, _ = date.today().isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        usage.setdefault(week_key, {})
        model_key = args.model or "unknown"
        usage[week_key][model_key] = round(usage[week_key].get(model_key, 0.0) + args.cost_usd, 6)
        # Also keep a per-day breakdown (last 30 days)
        usage.setdefault("daily", {})
        today_key = date.today().isoformat()
        usage["daily"].setdefault(today_key, {})
        usage["daily"][today_key][model_key] = round(usage["daily"][today_key].get(model_key, 0.0) + args.cost_usd, 6)
        # Trim daily to last 30 entries
        if len(usage["daily"]) > 30:
            keys = sorted(usage["daily"].keys())
            for old in keys[:-30]:
                del usage["daily"][old]
        tmp = usage_path + ".tmp"
        with open(tmp, "w") as f: json.dump(usage, f, indent=2)
        os.replace(tmp, usage_path)

    # Redraw the board
    subprocess.run([sys.executable, f"{C3R_BIN}/status_board.py", "update", "--state", args.state], check=False)

    # Threshold alerts
    if args.context_pct is not None and agent.get("thread_id"):
        thresholds = [25, 50, 75, 100]
        for t in thresholds:
            if prev_pct < t <= args.context_pct:
                user = os.environ.get("DISCORD_USER_ID", "")
                mention = f"<@{user}> " if user and t >= 75 else ""
                icon = "🟢" if t == 25 else "🟡" if t == 50 else "🟠" if t == 75 else "🔴"
                msg = f"{mention}{icon} **{args.agent}** context at **{args.context_pct}%** — "
                if t >= 75:
                    msg += "consider pruning RESEARCH_LOG.md or tightening scope before next iter."
                else:
                    msg += "heads up."
                subprocess.run([f"{C3R_BIN}/notify.py", "--thread", agent["thread_id"], msg], check=False)

    # Fail streak alert
    if args.fail and agent.get("fail_streak", 0) >= 3 and agent.get("thread_id"):
        user = os.environ.get("DISCORD_USER_ID", "")
        msg = f"<@{user}> 🔴 **{args.agent}** failed {agent['fail_streak']} iterations in a row. Circuit breaker will trip at 5."
        subprocess.run([f"{C3R_BIN}/notify.py", "--thread", agent["thread_id"], msg], check=False)

    return 0

if __name__ == "__main__":
    sys.exit(main())
