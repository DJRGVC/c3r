#!/usr/bin/env python3
"""
status_board.py — persistent Discord dashboard message for a c3r project.

Subcommands:
  init   --project NAME --channel CHANNEL_ID --state STATE_JSON
         Creates the board message (+ pins it) and one thread per agent listed
         in the state JSON. Writes board_message_id + per-agent thread_id back
         into the state file.

  update --state STATE_JSON
         Re-renders the board message in place (edit, not repost).

  bump   --state STATE_JSON
         Deletes the existing board message and reposts at the bottom. All
         agent threads remain linked to the project but are no longer attached
         to the old (deleted) parent — Discord keeps threads alive after parent
         deletion, so this is non-destructive to history.

State JSON schema (written at ~/.c3r/<project>/state.json):
{
  "project": "myproject",
  "channel_id": "...",
  "board_message_id": "...",
  "agents": [
    {"name": "policy", "role": "generic", "model": "claude-sonnet-4-6",
     "branch": "agent/policy", "worktree": "/path",
     "thread_id": "...", "status": "idle",
     "last_iter": 0, "last_iter_ts": null,
     "last_context_pct": 0, "fail_streak": 0}
  ],
  "paused": false
}
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

API = "https://discord.com/api/v10"

def req(method: str, path: str, body=None):
    token = os.environ["DISCORD_BOT_TOKEN"]
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{API}{path}", data=data, method=method)
    r.add_header("Authorization", f"Bot {token}")
    r.add_header("User-Agent", "c3r-status-board (0.1)")
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        print(f"[board] HTTP {e.code} {method} {path}: {e.read().decode(errors='replace')}", file=sys.stderr)
        raise

STATUS_EMOJI = {"idle": "⚪", "running": "🟢", "paused": "⏸", "error": "🔴", "stopped": "⚫"}

def render(state: dict) -> str:
    cap = state.get("max_agents", "?")
    total = len(state["agents"])
    lines = [f"## c3r · {state['project']}   `{total}/{cap} agents`"]
    if state.get("paused"):
        lines.append("**⏸ PAUSED** — agents will finish current iteration then halt.")
    lines.append("```")
    lines.append(f"{'AGENT':<18} {'STATUS':<8} {'MODEL':<10} {'ITER':<7} {'CTX%':>5} {'LAST':<10}")
    by_name = {a["name"]: a for a in state["agents"]}
    children = {}
    for a in state["agents"]:
        children.setdefault(a.get("parent"), []).append(a["name"])
    def row(name, depth):
        a = by_name[name]
        e = STATUS_EMOJI.get(a.get("status", "idle"), "·")
        model_short = a.get("model", "").replace("claude-", "").replace("-4-6", "").replace("-4-5-20251001", "")[:10]
        last_iter = f"#{a.get('last_iter', 0)}"
        ctx = a.get("last_context_pct", 0)
        ts = a.get("last_iter_ts")
        rel = ""
        if ts:
            try:
                dt = datetime.fromisoformat(ts)
                secs = int((datetime.now(timezone.utc) - dt).total_seconds())
                if secs < 60: rel = f"{secs}s"
                elif secs < 3600: rel = f"{secs // 60}m"
                else: rel = f"{secs // 3600}h"
            except Exception: pass
        prefix = ("  " * depth) + ("└ " if depth > 0 else "")
        label = (prefix + a["name"])[:18]
        lines.append(f"{e} {label:<16} {a.get('status','idle'):<8} {model_short:<10} {last_iter:<7} {ctx:>4}% {rel:<10}")
        for c in children.get(name, []):
            row(c, depth + 1)
    for root in children.get(None, []):
        row(root, 0)
    lines.append("```")
    lines.append(f"_updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    return "\n".join(lines)

def load_state(path: str) -> dict:
    with open(path) as f: return json.load(f)

def save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(state, f, indent=2)
    os.replace(tmp, path)

def cmd_init(args) -> int:
    state = load_state(args.state)
    channel = state["channel_id"]
    content = render(state)
    msg = req("POST", f"/channels/{channel}/messages", {"content": content})
    state["board_message_id"] = msg["id"]
    try:
        req("PUT", f"/channels/{channel}/pins/{msg['id']}")
    except Exception:
        print("[board] pin failed (bot may lack Manage Messages); continuing", file=sys.stderr)
    for a in state["agents"]:
        if a.get("thread_id"): continue
        # Descriptive title: "name · focus" (Discord caps at 100 chars)
        focus = a.get("focus", "") or ""
        title = f"{a['name']} · {focus}"[:100] if focus else a["name"]
        thread = req("POST", f"/channels/{channel}/threads",
                     {"name": title, "type": 11, "auto_archive_duration": 10080})  # 7 days
        a["thread_id"] = thread["id"]
        req("POST", f"/channels/{a['thread_id']}/messages",
            {"content": f"**{a['name']}** — {a.get('role','?')} · `{a.get('model','?')}`\n"
                        f"Focus: {a.get('focus','(not set)')}\n\n"
                        f"Reply in this thread to send the agent an INBOX message. "
                        f"Agent questions and alerts will appear here."})
    save_state(args.state, state)
    print(msg["id"])
    return 0

def cmd_update(args) -> int:
    state = load_state(args.state)
    if not state.get("board_message_id"):
        print("[board] no board_message_id in state; run init first", file=sys.stderr)
        return 1
    req("PATCH", f"/channels/{state['channel_id']}/messages/{state['board_message_id']}",
        {"content": render(state)})
    return 0

def cmd_bump(args) -> int:
    state = load_state(args.state)
    if state.get("board_message_id"):
        try:
            req("DELETE", f"/channels/{state['channel_id']}/messages/{state['board_message_id']}")
        except Exception:
            pass
    state["board_message_id"] = None
    save_state(args.state, state)
    return cmd_init(args)

def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("init", "update", "bump"):
        s = sub.add_parser(name)
        s.add_argument("--state", required=True)
    args = p.parse_args()
    return {"init": cmd_init, "update": cmd_update, "bump": cmd_bump}[args.cmd](args)

if __name__ == "__main__":
    sys.exit(main())
