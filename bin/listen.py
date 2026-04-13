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
  !c3r pause [agent]        Pause all agents, or one by name
  !c3r resume [agent]       Resume all agents, or one by name
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
C3R_BINARY = C3R_DIR / "c3r"

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
!c3r status              Bump the status board to bottom
!c3r pause [agent]       Pause all agents, or one by name
!c3r resume [agent]      Resume all agents, or one by name
!c3r ping <agent> <msg>  Send INBOX message to an agent
!c3r report              Rebuild + redeploy the Quarto site
!c3r write               Nudge agents to update Quarto pages
!c3r fix <task>          Spawn an ephemeral fix-it agent
```
To talk to an agent, just reply inside its thread — no command needed."""

def handle_channel_cmd(state, state_path, content, channel):
    parts = content.strip().split(None, 2)
    if len(parts) < 2: return
    cmd = parts[1].lower()
    # Always post the user-visible ack FIRST so confirmation never gets
    # lost behind a slow board update or transient subprocess failure.
    if cmd == "help":
        post(channel, HELP_TEXT)
    elif cmd == "status":
        post(channel, "🔄 Bumping status board...")
        subprocess.run([sys.executable, str(C3R_BIN / "status_board.py"), "bump", "--state", state_path], check=False)
    elif cmd == "pause":
        # !c3r pause [agent_name] — pause one agent or all
        agent_name = parts[2] if len(parts) > 2 else None
        if agent_name:
            matched = [a for a in state["agents"] if a["name"] == agent_name]
            if not matched:
                names = ", ".join(a["name"] for a in state["agents"])
                post(channel, f"⚠ No agent named `{agent_name}`. Available: {names}")
                return
            Path(matched[0]["worktree"]).joinpath(".c3r/PAUSED").touch()
            matched[0]["status"] = "paused"
            if all(Path(a["worktree"]).joinpath(".c3r/PAUSED").exists() for a in state["agents"]):
                state["paused"] = True
            save_state(state_path, state)
            post(channel, f"⏸ **PAUSE** `{agent_name}` — agent will halt after its current iteration. Use `!c3r resume {agent_name}` to continue.")
        else:
            for a in state["agents"]:
                Path(a["worktree"]).joinpath(".c3r/PAUSED").touch()
            state["paused"] = True; save_state(state_path, state)
            post(channel, "⏸ **PAUSE** — all agents will halt after their current iteration completes. Use `!c3r resume` to continue.")
        try:
            subprocess.run([sys.executable, str(C3R_BIN / "status_board.py"), "update", "--state", state_path], check=False, timeout=10)
        except Exception as e:
            print(f"[listen] board update after pause failed: {e}", file=sys.stderr)
    elif cmd == "resume":
        # !c3r resume [agent_name] — resume one agent or all
        agent_name = parts[2] if len(parts) > 2 else None
        if agent_name:
            matched = [a for a in state["agents"] if a["name"] == agent_name]
            if not matched:
                names = ", ".join(a["name"] for a in state["agents"])
                post(channel, f"⚠ No agent named `{agent_name}`. Available: {names}")
                return
            for flag in ("PAUSED", "PAUSED_QUOTA"):
                try: Path(matched[0]["worktree"]).joinpath(f".c3r/{flag}").unlink()
                except FileNotFoundError: pass
            matched[0]["status"] = "running"
            state["paused"] = False; save_state(state_path, state)
            post(channel, f"▶ **RESUME** `{agent_name}` — agent will pick up within ~30s.")
        else:
            for a in state["agents"]:
                try: Path(a["worktree"]).joinpath(".c3r/PAUSED").unlink()
                except FileNotFoundError: pass
            state["paused"] = False; save_state(state_path, state)
            post(channel, "▶ **RESUME** — agents will pick up from where they left off within ~30s.")
        try:
            subprocess.run([sys.executable, str(C3R_BIN / "status_board.py"), "update", "--state", state_path], check=False, timeout=10)
        except Exception as e:
            print(f"[listen] board update after resume failed: {e}", file=sys.stderr)
    elif cmd == "report":
        # Manual Quarto site rebuild. Runs c3r report publish in background.
        if not state.get("quarto_enabled") and not Path(state.get("project_root", os.path.dirname(os.path.dirname(state_path)))).joinpath("_quarto.yml").exists():
            post(channel, "⚠ Quarto report not enabled for this project. Run `c3r report init <path>` first.")
        else:
            project_root = os.path.dirname(os.path.dirname(state_path))
            site_url = state.get("quarto_site_url", "")
            post(channel, "🔄 Rebuilding Quarto site...")
            try:
                # Background — don't block the listener loop while quarto renders
                subprocess.Popen(
                    [str(C3R_BINARY), "report", "publish", project_root],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                post(channel, f"⚠ Failed to spawn rebuild: {e}")
    elif cmd == "write":
        # Nudge all top-level (parent=None) agents to update their Quarto page.
        # Sub-agents are excluded — they're scoped to short tasks and shouldn't
        # be writing to the public site.
        targets = [a for a in state["agents"]
                   if not a.get("parent") and a.get("status") != "stopped"
                   and not a["name"].startswith("c3r-fix-")
                   and not a["name"].startswith("fix-")
                   and a["name"] != "quarto-fixer"]
        if not targets:
            post(channel, "no top-level agents to nudge"); return
        msg = ("📝 WRITE NUDGE — please update your `agents/<name>.qmd` Quarto page "
               "with your latest results, decisions, or figures before your next experiment. "
               "Format reminder: see PROMPT.md 'Quarto report' section.")
        for a in targets:
            append_inbox(a["worktree"], "you (channel)", msg)
        # Record pending set so the main loop can auto-publish once all
        # nudged agents have committed an update to their .qmd page.
        state["quarto_write_pending"] = {
            "nudge_ts": time.time(),
            "agents": [a["name"] for a in targets],
        }
        save_state(state_path, state)
        post(channel, f"→ nudged {len(targets)} agent(s): " + ", ".join(f"`{a['name']}`" for a in targets) +
             "\n  (will auto-rebuild Quarto site once all have committed updates)")
    elif cmd == "fix":
        # Spawn an ephemeral fix-it agent. Name is fix-<word>-<HHMM> where
        # <word> is the first significant word in the task. Multiple can
        # coexist via the timestamp suffix. The c3r-fix- and fix- prefixes
        # are both recognized as ephemeral by cmd_kill.
        if len(parts) < 3:
            post(channel, "usage: `!c3r fix <task description>`"); return
        task = parts[2].strip()
        # Pick first non-stopword from the task to summarize the issue
        STOP = {"the","a","an","is","are","was","were","be","been","being","have","has","had",
                "do","does","did","will","would","could","should","may","might","must","can",
                "cannot","this","that","these","those","what","when","where","how","why","who",
                "which","just","also","but","or","and","if","then","than","so","not","no","yes",
                "very","really","still","again","here","there","seems","seem","my","your","our",
                "their","its","it","you","i","we","they","them","us","me","please","thanks",
                "thank","ok","okay","yeah","wait","actually","probably","maybe","perhaps",
                "much","many","some","any","more","less","most","every","each","all","both",
                "want","need","get","got","make","made","take","took","go","going","come","came",
                "tell","said","know","think","feel","help","new","old","good","bad","big","small"}
        import re as _re
        # Try a fast claude haiku call to generate a semantic slug. Falls
        # back to a stopword heuristic if claude is unavailable or returns
        # something we can't validate.
        slug = None
        try:
            r = subprocess.run(
                ["claude", "-p", "--model", "claude-haiku-4-5",
                 f"Summarize this task in 2-3 hyphenated lowercase words for a "
                 f"filesystem-safe slug. The slug should describe what the task "
                 f"is ABOUT (the noun/topic), not the action verb. Return ONLY "
                 f"the slug — no quotes, no explanation, no punctuation other "
                 f"than hyphens. Examples: 'the search bar in quarto disappeared' "
                 f"-> quarto-search-bar; 'remind perception of the goal' -> "
                 f"perception-goal-reminder. Task: {task}"],
                capture_output=True, text=True, timeout=20,
            )
            cand = (r.stdout or "").strip().splitlines()[-1].strip().lower()
            cand = _re.sub(r'[^a-z0-9-]', '', cand).strip('-')
            # Validate: 2-4 segments, each 2+ chars, total <= 40 chars
            segs = [s for s in cand.split('-') if s]
            if 2 <= len(segs) <= 4 and all(len(s) >= 2 for s in segs) and len(cand) <= 40:
                slug = '-'.join(segs)
        except Exception as e:
            print(f"[listen] haiku slug failed: {e} — falling back to heuristic", file=sys.stderr)
        if not slug:
            words = _re.findall(r'[a-zA-Z]+', task.lower())
            good = [w for w in words if len(w) >= 4 and w not in STOP]
            if len(good) >= 2:
                slug = f"{good[0]}-{good[1]}"
            elif good:
                slug = good[0]
            else:
                slug = "task"
        # Append -2, -3, ... only if a same-named agent already exists
        existing = {a["name"] for a in state["agents"]}
        fixer_name = f"fix-{slug}"
        n = 2
        while fixer_name in existing:
            fixer_name = f"fix-{slug}-{n}"
            n += 1
        project_root = os.path.dirname(os.path.dirname(state_path))
        short_focus = task[:80]  # clean Discord title
        brief = (f"🛠 ONE-SHOT TASK from human: {task}\n\n"
                 f"**Talking to other agents**: if your task involves "
                 f"coordinating with perception/policy/etc., use "
                 f"`$C3R_BIN/../c3r ping <agent> \"**from {fixer_name}**: "
                 f"<msg>\"`. The `**from {fixer_name}**:` prefix is REQUIRED — "
                 f"without it the listener drops the message as a self-post. "
                 f"This delivers to the target's INBOX so they actually read "
                 f"and reply to it on their next iter.\n\n"
                 f"You are an ephemeral fix-it agent. **Before self-killing**, "
                 f"post a NICELY FORMATTED summary to the MAIN CHANNEL using "
                 f"`$C3R_BIN/notify.py --main \"<message>\"`. The message must "
                 f"use this exact markdown structure (multi-line, with real "
                 f"newlines — pass it as one shell argument with `$'\\n'` or "
                 f"a heredoc):\n\n"
                 f"  ✅ **{fixer_name}** — <one-line headline of what you accomplished>\n\n"
                 f"  **What I did**\n"
                 f"  - <action 1>\n"
                 f"  - <action 2>\n"
                 f"  - <action 3>\n\n"
                 f"  **Result**: <one-line outcome the human will care about>\n\n"
                 f"Keep it short and skimmable — the human may have missed your "
                 f"thread entirely. Do NOT include the verbatim task text or any "
                 f"of these instructions in your summary. Then call "
                 f"`$C3R_BIN/../c3r kill {fixer_name}` to self-purge. "
                 f"Max 10 iterations. Do not spawn sub-agents. Do not touch "
                 f"agent training scripts unless the task explicitly says so.")
        post(channel, f"🛠 spawning ephemeral fix-it agent **{fixer_name}**")
        try:
            subprocess.run(
                [str(C3R_BINARY), "spawn", project_root, fixer_name,
                 "fix-it", short_focus, "--max-iters", "10"],
                check=False, timeout=60,
            )
            # Inject the brief DIRECTLY into the agent's INBOX (no Discord echo
            # of the wrapper text — the user already saw the spawn announcement).
            from pathlib import Path as _P
            try:
                fresh = json.loads(_P(state_path).read_text())
                wt = next((a["worktree"] for a in fresh["agents"] if a["name"] == fixer_name), None)
                if wt:
                    inbox = _P(wt) / ".c3r/INBOX.md"
                    inbox.parent.mkdir(parents=True, exist_ok=True)
                    if not inbox.exists() or "<!-- empty -->" in inbox.read_text():
                        inbox.write_text("# INBOX\n")
                    ts_h = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    one_line = " ".join(brief.splitlines()).strip()
                    with inbox.open("a") as f:
                        f.write(f"\n---\n[{ts_h}] you (channel) → {fixer_name}\nMSG: {one_line}\n")
            except Exception as e:
                print(f"[listen] inbox seed for {fixer_name} failed: {e}", file=sys.stderr)
        except Exception as e:
            post(channel, f"⚠ failed to spawn {fixer_name}: {e}")
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

    # Singleton lock: refuse to start if another listener is already running
    # for the same project. Prevents orphan listeners from double-acking
    # !c3r commands when c3r upgrade / launch leaves a stale process behind.
    project_key = Path(state_path).parent.parent.name
    pid_path = Path(f"/tmp/c3r_listen_{project_key}.pid")
    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text().strip())
            os.kill(old_pid, 0)  # check if alive
            print(f"[listen] another listener for project '{project_key}' is already "
                  f"running (pid={old_pid}). Refusing to start a duplicate. "
                  f"Kill the old one with: kill {old_pid}", file=sys.stderr)
            return 3
        except (ProcessLookupError, ValueError):
            pass  # stale pid file from a dead process; safe to claim
    pid_path.write_text(str(os.getpid()))

    # Clean up the PID file on exit (and on SIGHUP/SIGTERM from tmux kill)
    import atexit, signal
    def _cleanup(*_):
        try: pid_path.unlink()
        except FileNotFoundError: pass
        sys.exit(0)
    atexit.register(_cleanup)
    signal.signal(signal.SIGHUP, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    # Read channel from state.json — NOT from env. The env var holds only
    # one channel (whichever project was set up most recently in
    # ~/.config/c3r/config.env), so multi-project setups would have all
    # listeners polling the wrong channel if we trusted env.
    state_initial = load_state(state_path)
    channel = state_initial.get("channel_id") or os.environ.get("DISCORD_CHANNEL_ID")
    if not channel:
        print("[listen] FATAL: no channel_id in state.json or DISCORD_CHANNEL_ID env", file=sys.stderr)
        return 4
    me = req("GET", "/users/@me")
    if not me:
        print("[listen] FATAL: could not fetch bot identity", file=sys.stderr); return 1
    bot_id = me["id"]

    # On startup, advance every cursor to the current latest message so a
    # restart never re-processes pre-restart messages. The /tmp cursor file
    # was originally meant for crash recovery but caused duplicate processing
    # on intentional restarts (the file was older than the latest message
    # in the channel, so the new listener re-saw recent !c3r commands and
    # re-processed them, double-acking the user's pause/resume).
    cursor_path = Path(f"/tmp/c3r_listen_{Path(state_path).parent.parent.name}.cursors.json")
    last_channel_id = None
    last_thread_ids: dict[str, str] = {}
    try:
        latest = req("GET", f"/channels/{channel}/messages?limit=1") or []
        if latest:
            last_channel_id = latest[0]["id"]
            print(f"[listen] startup cursor: channel @ {last_channel_id}", file=sys.stderr)
    except Exception as e:
        print(f"[listen] could not fetch latest channel msg: {e}", file=sys.stderr)
    for a in state_initial.get("agents", []):
        tid = a.get("thread_id")
        if not tid: continue
        try:
            latest = req("GET", f"/channels/{tid}/messages?limit=1") or []
            if latest:
                last_thread_ids[tid] = latest[0]["id"]
        except Exception: pass

    def save_cursors():
        try:
            tmp = str(cursor_path) + ".tmp"
            Path(tmp).write_text(json.dumps({"channel": last_channel_id, "threads": last_thread_ids}))
            os.replace(tmp, cursor_path)
        except Exception as e:
            print(f"[listen] could not save cursors: {e}", file=sys.stderr)

    print(f"[listen] up — project={state_initial.get('project','?')} bot_id={bot_id} channel={channel}", file=sys.stderr)
    for a in state_initial.get("agents", []):
        print(f"[listen]   agent {a['name']} → thread {a.get('thread_id')} worktree {a['worktree']}", file=sys.stderr)

    # Auto-refresh the pinned status board every BOARD_REFRESH_SEC, even if
    # no agent has fired a heartbeat. Iterations can take an hour, so the
    # board would otherwise show very stale "LAST" timestamps.
    BOARD_REFRESH_SEC = 60
    last_board_update = 0.0

    # Auto-publish the Quarto report every QUARTO_PUBLISH_INTERVAL_SEC if
    # quarto_enabled in state.json. The publish is run in the background
    # so it doesn't block listener polling.
    QUARTO_PUBLISH_INTERVAL_SEC = 3600  # 60 min default; configurable in state.json
    last_quarto_publish = 0.0
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
                    if not content: continue
                    if author_id == bot_id:
                        # Same bot account → could be (a) the agent's own
                        # outbound posts to its own thread, or (b) ANOTHER
                        # c3r agent posting cross-thread (e.g. fix-bot
                        # delivering a heads-up to policy). Identify
                        # cross-agent messages by the "from <name>:" prefix
                        # convention and route them to INBOX. Self-posts
                        # without that prefix are still skipped.
                        m_author = None
                        import re as _re
                        mf = _re.match(r'^(?:📨|🛠|⚠|✅|↩|📊)?\s*\*\*from\s+([a-zA-Z0-9_-]+)\*\*[:\s]', content)
                        if mf:
                            m_author = mf.group(1)
                        if not m_author:
                            continue  # bot self-post; skip
                        append_inbox(a["worktree"], m_author, content)
                        continue
                    append_inbox(a["worktree"], m["author"].get("global_name") or m["author"]["username"], content)
                    try:
                        req("PUT", f"/channels/{tid}/messages/{m['id']}/reactions/{urllib.parse.quote('✅')}/@me")
                    except Exception: pass

            # Save cursors IMMEDIATELY after message processing, not at the
            # end of the loop iteration. Otherwise an exception in the board
            # refresh below would prevent cursor advance, causing the next
            # poll to re-process the same messages and double-ack !c3r cmds.
            save_cursors()

            # 3. Periodic status board refresh (every 60s wall-clock)
            if time.time() - last_board_update >= BOARD_REFRESH_SEC:
                try:
                    subprocess.run(
                        [sys.executable, str(C3R_BIN / "status_board.py"),
                         "update", "--state", state_path],
                        check=False, timeout=10,
                    )
                    last_board_update = time.time()
                except Exception as e:
                    print(f"[listen] board refresh failed: {e}", file=sys.stderr)

            # 3.5. Auto-publish trigger: if `!c3r write` left a pending set,
            # check each nudged agent's branch for a new commit touching
            # agents/<name>.qmd since the nudge. When all are done, fire
            # `c3r report publish` and clear the pending set.
            pending = state.get("quarto_write_pending")
            if pending and pending.get("agents"):
                project_root = os.path.dirname(os.path.dirname(state_path))
                nudge_ts = pending.get("nudge_ts", 0)
                since = datetime.fromtimestamp(nudge_ts, tz=timezone.utc).isoformat()
                still_waiting = []
                for name in pending["agents"]:
                    r = subprocess.run(
                        ["git", "-C", project_root, "log", f"agent/{name}",
                         f"--since={since}", "--format=%H", "--", f"agents/{name}.qmd"],
                        capture_output=True, text=True,
                    )
                    if not (r.returncode == 0 and r.stdout.strip()):
                        still_waiting.append(name)
                if not still_waiting:
                    print(f"[listen] all nudged agents updated their Quarto pages — auto-publishing", file=sys.stderr)
                    post(channel, "✅ All nudged agents updated their pages — auto-rebuilding site...")
                    state.pop("quarto_write_pending", None)
                    save_state(state_path, state)
                    try:
                        subprocess.Popen(
                            [str(C3R_BINARY), "report", "publish", project_root],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    except Exception as e:
                        print(f"[listen] auto-publish spawn failed: {e}", file=sys.stderr)
                else:
                    # Update pending in case we want to track progress later
                    pending["agents"] = still_waiting

            # 4. Periodic Quarto report publish (default 60 min)
            interval = state.get("quarto_publish_interval_min", 60) * 60
            if (state.get("quarto_enabled")
                    and time.time() - last_quarto_publish >= interval):
                project_root = os.path.dirname(os.path.dirname(state_path))
                if Path(project_root, "_quarto.yml").exists():
                    print(f"[listen] auto-publishing Quarto site (interval={interval}s)", file=sys.stderr)
                    try:
                        subprocess.Popen(
                            [str(C3R_BINARY), "report", "publish", project_root],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                        last_quarto_publish = time.time()
                    except Exception as e:
                        print(f"[listen] quarto auto-publish failed: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[listen] loop error: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    sys.exit(main())
