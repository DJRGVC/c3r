#!/usr/bin/env python3
"""
listen.py — Discord-side listener that bridges:

  1. New non-bot messages in each agent's thread  →  append to <worktree>/.c3r/INBOX.md
  2. `!c3r <cmd>` messages in the main channel    →  trigger local c3r action

Runs as a long-lived process (launched in its own tmux window by `c3r launch`).
Pure stdlib REST polling; no gateway/websocket, no open ports.

Supported channel commands:
  !c3r help                 List commands
  !c3r status               Bump the status board to the bottom of the channel
  !c3r pause                Pause all agents cooperatively
  !c3r resume               Resume all agents
  !c3r ping <agent> <msg>   Send a message to a specific agent (same as replying in its thread)

Env required: DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, DISCORD_USER_ID, C3R_STATE
"""
from __future__ import annotations
import json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://discord.com/api/v10"
POLL_INTERVAL = 4.0
C3R_BIN = Path(os.path.realpath(__file__)).parent
C3R_DIR = C3R_BIN.parent

def req(method, path, body=None):
    token = os.environ["DISCORD_BOT_TOKEN"]
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{API}{path}", data=data, method=method)
    r.add_header("Authorization", f"Bot {token}")
    r.add_header("User-Agent", "c3r-listen (0.1)")
    if data: r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        print(f"[listen] HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        return None

def load_state(path): return json.loads(Path(path).read_text())
def save_state(path, s):
    Path(path + ".tmp").write_text(json.dumps(s, indent=2))
    os.replace(path + ".tmp", path)

def post(target, content):
    return req("POST", f"/channels/{target}/messages", {"content": content, "allowed_mentions": {"parse": []}})

def append_inbox(worktree: str, author: str, content: str):
    inbox = Path(worktree) / ".c3r" / "INBOX.md"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    if not inbox.exists() or "<!-- empty -->" in inbox.read_text():
        inbox.write_text("# INBOX\n\n")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with inbox.open("a") as f:
        f.write(f"\n---\n**{author}** · {ts}\n\n{content}\n")
    print(f"[listen] inbox ← {worktree} from {author}: {content[:60]}", file=sys.stderr)

# ---------- channel command handlers ----------

HELP_TEXT = """**c3r Discord commands** (main channel)
```
!c3r help                List commands
!c3r status              Bump the status board to the bottom
!c3r pause               Pause all agents (finishes current iter first)
!c3r resume              Resume all agents
!c3r ping <agent> <msg>  Message a specific agent (same as replying in thread)
```
To talk to an agent, just reply inside its thread — no command needed."""

def handle_channel_cmd(state, state_path, content, channel):
    parts = content.strip().split(None, 2)
    if len(parts) < 2: return
    cmd = parts[1].lower()
    if cmd == "help":
        post(channel, HELP_TEXT)
    elif cmd == "status":
        subprocess.run([sys.executable, str(C3R_BIN / "status_board.py"), "bump", "--state", state_path], check=False)
    elif cmd == "pause":
        for a in state["agents"]:
            Path(a["worktree"]).joinpath(".c3r/PAUSED").touch()
        state["paused"] = True; save_state(state_path, state)
        subprocess.run([sys.executable, str(C3R_BIN / "status_board.py"), "update", "--state", state_path], check=False)
        post(channel, "⏸ All agents will pause after their current iteration.")
    elif cmd == "resume":
        for a in state["agents"]:
            try: Path(a["worktree"]).joinpath(".c3r/PAUSED").unlink()
            except FileNotFoundError: pass
        state["paused"] = False; save_state(state_path, state)
        subprocess.run([sys.executable, str(C3R_BIN / "status_board.py"), "update", "--state", state_path], check=False)
        post(channel, "▶ Agents resumed.")
    elif cmd == "ping":
        if len(parts) < 3:
            post(channel, "usage: `!c3r ping <agent> <message>`"); return
        rest = parts[2]; name, _, msg = rest.partition(" ")
        agent = next((a for a in state["agents"] if a["name"] == name), None)
        if not agent:
            post(channel, f"no agent named `{name}`"); return
        append_inbox(agent["worktree"], "you (channel)", msg.strip())
        post(channel, f"→ delivered to **{name}** inbox")
    else:
        post(channel, f"unknown command `{cmd}` — try `!c3r help`")

# ---------- main loop ----------

def main() -> int:
    state_path = os.environ.get("C3R_STATE")
    if not state_path or not os.path.isfile(state_path):
        print("[listen] missing C3R_STATE", file=sys.stderr); return 2
    channel = os.environ["DISCORD_CHANNEL_ID"]
    bot_id = req("GET", "/users/@me")["id"]

    last_channel_id = None  # last seen message id in main channel
    last_thread_ids: dict[str, str] = {}  # thread_id -> last message id

    print("[listen] up", file=sys.stderr)
    while True:
        try:
            state = load_state(state_path)

            # 1. Poll main channel for !c3r commands
            q = f"?limit=10" + (f"&after={last_channel_id}" if last_channel_id else "")
            msgs = req("GET", f"/channels/{channel}/messages{q}") or []
            msgs.sort(key=lambda m: int(m["id"]))
            for m in msgs:
                last_channel_id = m["id"]
                if m["author"]["id"] == bot_id: continue
                content = (m.get("content") or "").strip()
                if content.lower().startswith("!c3r"):
                    handle_channel_cmd(state, state_path, content, channel)

            # 2. Poll each agent thread for new non-bot messages
            for a in state["agents"]:
                tid = a.get("thread_id")
                if not tid: continue
                after = last_thread_ids.get(tid)
                q = f"?limit=10" + (f"&after={after}" if after else "")
                tmsgs = req("GET", f"/channels/{tid}/messages{q}") or []
                tmsgs.sort(key=lambda m: int(m["id"]))
                for m in tmsgs:
                    last_thread_ids[tid] = m["id"]
                    if m["author"]["id"] == bot_id: continue
                    content = (m.get("content") or "").strip()
                    if not content: continue
                    append_inbox(a["worktree"], m["author"].get("global_name") or m["author"]["username"], content)
                    # ✓ reaction to acknowledge receipt
                    try:
                        req("PUT", f"/channels/{tid}/messages/{m['id']}/reactions/{urllib.parse.quote('✅')}/@me")
                    except Exception: pass

        except Exception as e:
            print(f"[listen] loop error: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    sys.exit(main())
