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
VERBOSE = os.environ.get("C3R_LISTEN_VERBOSE", "0") == "1"
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
    """Append a message to INBOX.md in a strict parseable format:

        ---
        [YYYY-MM-DD HH:MM UTC] <author> → <agent>
        MSG: <single-line message>

    The agent later moves this to INBOX_ARCHIVE.md and appends `RESP: ...`.
    """
    inbox = Path(worktree) / ".c3r" / "INBOX.md"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    if not inbox.exists() or "<!-- empty -->" in inbox.read_text():
        inbox.write_text("# INBOX\n")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    agent = Path(worktree).name.split("-")[-1]
    # Collapse message to one line (strip newlines) for easy parsing
    one_line = " ".join(content.splitlines()).strip()
    with inbox.open("a") as f:
        f.write(f"\n---\n[{ts}] {author} → {agent}\nMSG: {one_line}\n")
    print(f"[listen] inbox ← {worktree} from {author}: {one_line[:60]}", file=sys.stderr)

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
    me = req("GET", "/users/@me")
    if not me:
        print("[listen] FATAL: could not fetch bot identity", file=sys.stderr); return 1
    bot_id = me["id"]

    # Persist cursors to /tmp so a crash + restart doesn't re-ingest old
    # messages as duplicate INBOX entries.
    cursor_path = Path(f"/tmp/c3r_listen_{Path(state_path).parent.parent.name}.cursors.json")
    if cursor_path.exists():
        try:
            saved = json.loads(cursor_path.read_text())
            last_channel_id = saved.get("channel")
            last_thread_ids = saved.get("threads", {})
            print(f"[listen] restored cursors from {cursor_path}", file=sys.stderr)
        except Exception as e:
            print(f"[listen] could not restore cursors: {e}", file=sys.stderr)
            last_channel_id, last_thread_ids = None, {}
    else:
        last_channel_id = None
        last_thread_ids: dict[str, str] = {}

    def save_cursors():
        try:
            tmp = str(cursor_path) + ".tmp"
            Path(tmp).write_text(json.dumps({"channel": last_channel_id, "threads": last_thread_ids}))
            os.replace(tmp, cursor_path)
        except Exception as e:
            print(f"[listen] could not save cursors: {e}", file=sys.stderr)

    print(f"[listen] up — bot_id={bot_id} channel={channel}", file=sys.stderr)
    state0 = load_state(state_path)
    for a in state0.get("agents", []):
        print(f"[listen]   agent {a['name']} → thread {a.get('thread_id')} worktree {a['worktree']}", file=sys.stderr)
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
                q = f"?limit=20" + (f"&after={after}" if after else "")
                tmsgs = req("GET", f"/channels/{tid}/messages{q}") or []
                if VERBOSE:
                    print(f"[listen] poll {a['name']} thread={tid} after={after} got={len(tmsgs)}", file=sys.stderr)
                tmsgs.sort(key=lambda m: int(m["id"]))
                for m in tmsgs:
                    last_thread_ids[tid] = m["id"]
                    author_id = m["author"]["id"]
                    content = (m.get("content") or "").strip()
                    if VERBOSE:
                        print(f"[listen]   msg id={m['id']} author={author_id} bot={author_id==bot_id} content={content[:60]!r}", file=sys.stderr)
                    if author_id == bot_id: continue
                    if not content: continue
                    append_inbox(a["worktree"], m["author"].get("global_name") or m["author"]["username"], content)
                    try:
                        req("PUT", f"/channels/{tid}/messages/{m['id']}/reactions/{urllib.parse.quote('✅')}/@me")
                    except Exception: pass

            save_cursors()
        except Exception as e:
            print(f"[listen] loop error: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    sys.exit(main())
