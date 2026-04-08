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

# Discord embed color stripe (decimal RGB)
COLOR_GREEN  = 0x57F287   # all healthy
COLOR_YELLOW = 0xFEE75C   # warnings (paused, high context, mid-activity)
COLOR_RED    = 0xED4245   # any agent errored or quota-paused
COLOR_GREY   = 0x99AAB5   # all stopped or unknown

def _health_color(state: dict) -> int:
    agents = state.get("agents", [])
    active = [a for a in agents if a.get("status") != "stopped"]
    if not active: return COLOR_GREY
    if state.get("paused"): return COLOR_YELLOW
    for a in active:
        if a.get("fail_streak", 0) >= 3: return COLOR_RED
        if a.get("status") == "error":  return COLOR_RED
        if a.get("last_context_pct", 0) >= 75: return COLOR_RED
    for a in active:
        if a.get("last_context_pct", 0) >= 50: return COLOR_YELLOW
    return COLOR_GREEN

def _ctx_glyph(pct: int) -> str:
    """Tiny progress bar for context %."""
    if pct >= 90: return "█████"
    if pct >= 75: return "████░"
    if pct >= 50: return "███░░"
    if pct >= 25: return "██░░░"
    if pct >  0:  return "█░░░░"
    return "░░░░░"

def fetch_usage_data() -> dict | None:
    """Call claude_usage.py and return the structured data (dict) or None
    if unavailable. Lets the renderer build proper embed fields with
    progress bars and reset timestamps."""
    import subprocess, sys as _sys
    try:
        usage_script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "claude_usage.py")
        proc = subprocess.run([_sys.executable, usage_script], capture_output=True, text=True, timeout=8)
        if proc.returncode != 0: return None
        d = json.loads(proc.stdout)
        if d.get("source") != "claude.ai_live": return None
        return d
    except Exception:
        return None

def _bar10(pct: float) -> str:
    """10-cell unicode progress bar for embed fields."""
    if pct is None: return "──────────"
    filled = int(round(pct / 10))
    filled = max(0, min(10, filled))
    return "█" * filled + "░" * (10 - filled)

def _resets_in(ts_str: str | None) -> str:
    if not ts_str: return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z","+00:00"))
        secs = int((dt - datetime.now(dt.tzinfo)).total_seconds())
        if secs <= 0: return "now"
        if secs < 3600: return f"{secs // 60}m"
        if secs < 86400: return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"
        return f"{secs // 86400}d{(secs % 86400) // 3600}h"
    except Exception:
        return ""

def _usage_fields(usage: dict | None) -> list:
    """Build embed fields for usage windows (no plan field — that's in the title).
    Returns [] if no data."""
    if not usage: return []
    fh = usage.get("five_hour") or {}
    sd = usage.get("seven_day") or {}
    sd_son = usage.get("seven_day_sonnet") or {}
    sd_opus = usage.get("seven_day_opus") or {}

    def fmt_window(label, w):
        p = w.get("utilization")
        if p is None: return None
        bar = _bar10(p)
        rel = _resets_in(w.get("resets_at"))
        body = f"`{bar}`\n**{p:.0f}%**" + (f" · resets {rel}" if rel else "")
        return {"name": label, "value": body, "inline": True}

    fields = []
    for label, w in (("5h window", fh), ("7d window", sd), ("7d · sonnet", sd_son)):
        f = fmt_window(label, w)
        if f: fields.append(f)
    opus = fmt_window("7d · opus", sd_opus)
    if opus: fields.append(opus)
    # Pad to fill the row so the agent field below starts on a clean line
    while len(fields) % 3 != 0:
        fields.append({"name": "\u200b", "value": "\u200b", "inline": True})
    return fields

def _rel_time(ts_str: str | None) -> str:
    if not ts_str: return "—"
    try:
        dt = datetime.fromisoformat(ts_str)
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 60: return f"{secs}s ago"
        if secs < 3600: return f"{secs // 60}m ago"
        if secs < 86400: return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return "—"

def render_embed(state: dict) -> dict:
    """Build a rich Discord embed for the status board."""
    cap = state.get("max_agents", "?")
    agents = state.get("agents", [])
    active_n = sum(1 for a in agents if a.get("status") != "stopped")
    stopped_n = sum(1 for a in agents if a.get("status") == "stopped")

    # Description = paused badge ONLY (or empty). The agent count moves
    # to the bottom of the agent field for a cleaner top→bottom flow.
    desc_lines = []
    if state.get("paused"):
        desc_lines.append("⏸ **PAUSED** — agents will halt after their current iteration")

    # ── Build agent tree ──
    by_name = {a["name"]: a for a in agents}
    children = {}
    for a in agents:
        children.setdefault(a.get("parent"), []).append(a["name"])

    # Tighter table — drop the STATUS text column (emoji shows it),
    # drop "ago" from LAST (less noise), give names a bit more room
    table_lines = []

    def row(name, depth):
        a = by_name[name]
        st = a.get("status", "idle")
        e = STATUS_EMOJI.get(st, "·")
        model_short = a.get("model", "").replace("claude-", "").replace("-4-6", "").replace("-4-5-20251001", "")[:6]
        iter_n = f"#{a.get('last_iter', 0)}"
        ctx = a.get("last_context_pct", 0)
        ctx_str = f"{_ctx_glyph(ctx)} {ctx:>3}%"
        rel = _rel_time(a.get("last_iter_ts")).replace(" ago", "")
        prefix = "  " * depth + ("└ " if depth > 0 else "")
        label = f"{e} {prefix}{a['name']}"[:22]
        table_lines.append(f"{label:<22} {model_short:<6} {iter_n:<5} {ctx_str:<10} {rel:>6}")
        # Inline warnings under the row when notable
        badges = []
        if a.get("fail_streak", 0) >= 3:
            badges.append(f"⚠ fail_streak={a['fail_streak']}")
        if ctx >= 75 and st != "stopped":
            badges.append(f"⚠ context near full")
        if a.get("status") == "error":
            badges.append("⚠ last iter errored")
        if badges:
            table_lines.append(f"{' ' * 22} {' · '.join(badges)}")
        for c in children.get(name, []):
            row(c, depth + 1)

    for root in children.get(None, []):
        row(root, 0)

    # Capacity line goes UNDER the agents inside the same code block
    cap_str = f"{active_n}/{cap} active"
    if stopped_n: cap_str += f" · {stopped_n} stopped"
    table_lines.append("─" * 56)
    table_lines.append(cap_str)

    table_block = "```\n" + "\n".join(table_lines) + "\n```"

    fields = _usage_fields(fetch_usage_data())
    fields.append({
        "name": "Agents",
        "value": table_block,
        "inline": False,
    })

    embed = {
        "title": f"c3r · {state['project']}",
        "color": _health_color(state),
        "fields": fields,
        "footer": {
            "text": f"updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ·  auto-refresh 60s"
        },
    }
    if desc_lines:
        embed["description"] = "\n".join(desc_lines)
    return embed

# Backwards-compatible plain-text renderer (used by `c3r status` console output).
def render(state: dict) -> str:
    e = render_embed(state)
    return f"## {e['title']}\n{e['description']}\n_{e['footer']['text']}_"

def load_state(path: str) -> dict:
    with open(path) as f: return json.load(f)

def save_state(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(state, f, indent=2)
    os.replace(tmp, path)

def _suppress_pin_notification(channel: str, board_msg_id: str) -> None:
    """When you PIN a message via the Discord API, Discord auto-posts a
    'X pinned a message to this channel' system message (type=6). It's
    spammy on every bump. We delete it right after pinning. Requires the
    bot's Manage Messages permission (which it already has for pinning)."""
    try:
        msgs = req("GET", f"/channels/{channel}/messages?limit=10") or []
        for m in msgs:
            # Type 6 = CHANNEL_PINNED_MESSAGE; we only delete those that
            # reference our just-created board message id
            if m.get("type") == 6:
                ref = (m.get("message_reference") or {}).get("message_id")
                if ref == board_msg_id:
                    req("DELETE", f"/channels/{channel}/messages/{m['id']}")
                    return
    except Exception as e:
        print(f"[board] could not delete pin-notification system message: {e}", file=sys.stderr)

def cmd_init(args) -> int:
    state = load_state(args.state)
    channel = state["channel_id"]
    embed = render_embed(state)
    msg = req("POST", f"/channels/{channel}/messages", {"embeds": [embed]})
    state["board_message_id"] = msg["id"]
    try:
        req("PUT", f"/channels/{channel}/pins/{msg['id']}")
        _suppress_pin_notification(channel, msg["id"])
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
    # PATCH with embeds; clear `content` to avoid leftover plain text from
    # older boards rendered before the embed migration.
    req("PATCH", f"/channels/{state['channel_id']}/messages/{state['board_message_id']}",
        {"embeds": [render_embed(state)], "content": ""})
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
