#!/usr/bin/env python3
"""
ask_human.py — Human-in-the-loop bridge for Claude Code research agents via Discord.

Modes:
  Free-text:     ask_human.py "Question text"
  Single-choice: ask_human.py "Question" --choices "opt A" "opt B" "opt C"
  Multi-select:  ask_human.py "Question" --multi --choices "a" "b" "c"

Returns chosen text (or " | "-joined for multi) on stdout.
On timeout (default 15 min), prints TIMEOUT_SENTINEL and exits 0 so the agent
can continue rather than hang.

Env vars required:
  DISCORD_BOT_TOKEN    Bot token from Discord Developer Portal
  DISCORD_CHANNEL_ID   Target channel id (enable dev mode → right-click channel → Copy ID)
  DISCORD_USER_ID      Your user id (right-click yourself → Copy ID). Used to filter
                       reactions/messages so other channel members don't trigger replies.

Pure stdlib. No websockets, no webhook server. REST polling only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://discord.com/api/v10"
TIMEOUT_SENTINEL = "TIMEOUT_NO_HUMAN_RESPONSE"
POLL_INTERVAL = 3.0  # seconds
DEFAULT_TIMEOUT_MIN = 15

# Regional-indicator emojis (A–J). 10 options is more than any reasonable MCQ.
LETTER_EMOJI = [
    "\U0001F1E6", "\U0001F1E7", "\U0001F1E8", "\U0001F1E9", "\U0001F1EA",
    "\U0001F1EB", "\U0001F1EC", "\U0001F1ED", "\U0001F1EE", "\U0001F1EF",
]
SUBMIT_EMOJI = "\u2705"  # ✅

# ---------- Discord REST helpers ----------

def _req(method: str, path: str, token: str, body: dict | None = None) -> dict | list | None:
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bot {token}")
    req.add_header("User-Agent", "c3r-ask-human (https://github.com/djrgvc/c3r, 0.1)")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        if e.code == 429:
            # Expected under heavy polling — back off silently, caller will retry next tick.
            try:
                retry = json.loads(err_body).get("retry_after", 2)
                time.sleep(float(retry) + 0.5)
            except Exception:
                time.sleep(2)
        else:
            print(f"[ask_human] HTTP {e.code} on {method} {path}: {err_body}", file=sys.stderr)
        raise


def send_message(token: str, channel_id: str, content: str) -> str:
    resp = _req("POST", f"/channels/{channel_id}/messages", token, {"content": content})
    return resp["id"]  # type: ignore[index]


def add_reaction(token: str, channel_id: str, message_id: str, emoji: str) -> None:
    safe = urllib.parse.quote(emoji)
    _req("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{safe}/@me", token)


def get_message(token: str, channel_id: str, message_id: str) -> dict:
    resp = _req("GET", f"/channels/{channel_id}/messages/{message_id}", token)
    return resp or {}  # type: ignore[return-value]


def get_reaction_users(token: str, channel_id: str, message_id: str, emoji: str) -> list[dict]:
    safe = urllib.parse.quote(emoji)
    resp = _req("GET", f"/channels/{channel_id}/messages/{message_id}/reactions/{safe}?limit=100", token)
    return resp or []  # type: ignore[return-value]


def get_recent_messages(token: str, channel_id: str, after_id: str | None) -> list[dict]:
    q = f"?limit=20"
    if after_id:
        q += f"&after={after_id}"
    resp = _req("GET", f"/channels/{channel_id}/messages{q}", token)
    return resp or []  # type: ignore[return-value]


# ---------- Modes ----------

def _question_banner(question: str, deadline: float) -> str:
    """Make agent questions visually unmistakable in the Discord thread."""
    agent = os.environ.get("C3R_AGENT_NAME", "agent")
    timeout_min = int((deadline - time.time()) / 60)
    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"❓ **QUESTION from `{agent}`**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{question}\n\n"
        f"*Reply in this thread within {timeout_min} min, or I'll pick a fallback and post my decision here.*"
    )

def free_text(token: str, channel_id: str, user_id: str, question: str, deadline: float) -> str:
    header_id = send_message(token, channel_id, _question_banner(question, deadline))
    while time.time() < deadline:
        msgs = get_recent_messages(token, channel_id, after_id=header_id)
        # Discord returns newest first when paginating by after; filter to user, pick oldest new
        user_msgs = [m for m in msgs if m.get("author", {}).get("id") == user_id]
        if user_msgs:
            user_msgs.sort(key=lambda m: int(m["id"]))
            reply = user_msgs[0]["content"].strip()
            if reply:
                return reply
        time.sleep(POLL_INTERVAL)
    return TIMEOUT_SENTINEL


def _render_choices(question: str, choices: list[str], multi: bool) -> str:
    agent = os.environ.get("C3R_AGENT_NAME", "agent")
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"❓ **QUESTION from `{agent}`**",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        question,
        "",
    ]
    for i, c in enumerate(choices):
        lines.append(f"{LETTER_EMOJI[i]}  {c}")
    lines.append("")
    if multi:
        lines.append(f"*Tap all that apply, then tap {SUBMIT_EMOJI} to submit.*")
    else:
        lines.append("*Tap one reaction to answer. I'll pick a fallback if you don't reply within 15 min.*")
    return "\n".join(lines)


def choice_mode(
    token: str,
    channel_id: str,
    user_id: str,
    question: str,
    choices: list[str],
    multi: bool,
    deadline: float,
) -> str:
    if len(choices) > len(LETTER_EMOJI):
        print(f"[ask_human] Too many choices ({len(choices)} > {len(LETTER_EMOJI)})", file=sys.stderr)
        sys.exit(2)

    msg_id = send_message(token, channel_id, _render_choices(question, choices, multi))
    emojis = LETTER_EMOJI[: len(choices)]
    for e in emojis:
        add_reaction(token, channel_id, msg_id, e)
        time.sleep(0.3)  # gentle on rate limits
    if multi:
        add_reaction(token, channel_id, msg_id, SUBMIT_EMOJI)

    selected: set[int] = set()
    emoji_idx = {e: i for i, e in enumerate(emojis)}
    while time.time() < deadline:
        try:
            msg = get_message(token, channel_id, msg_id)
            # message.reactions is a list of {emoji:{name}, count, me:bool} objects.
            # It only tells us *whether* user_id voted if we fetch that reaction's user list,
            # but message.reactions excludes the bot's own preseed when we check count > 1.
            candidates = []
            submit_hit = False
            for r in msg.get("reactions") or []:
                name = (r.get("emoji") or {}).get("name", "")
                if r.get("count", 0) > 1:  # >1 means at least one non-bot voter
                    if name in emoji_idx:
                        candidates.append(name)
                    elif name == SUBMIT_EMOJI:
                        submit_hit = True
            # For any candidate, do one user-list fetch to confirm it's *our* user.
            for name in candidates:
                users = get_reaction_users(token, channel_id, msg_id, name)
                if any(u.get("id") == user_id for u in users):
                    idx = emoji_idx[name]
                    if not multi:
                        return choices[idx]
                    selected.add(idx)
            if multi and submit_hit and selected:
                users = get_reaction_users(token, channel_id, msg_id, SUBMIT_EMOJI)
                if any(u.get("id") == user_id for u in users):
                    return " | ".join(choices[i] for i in sorted(selected))
        except urllib.error.HTTPError:
            pass  # already logged on first 429; retry next tick
        time.sleep(POLL_INTERVAL)
    return TIMEOUT_SENTINEL


# ---------- Entry point ----------

def main() -> int:
    p = argparse.ArgumentParser(description="Ask a human via Discord and wait for a reply.")
    p.add_argument("question", help="Question text")
    p.add_argument("--choices", nargs="+", help="Enumerated options; triggers reaction poll mode")
    p.add_argument("--multi", action="store_true", help="Allow multi-select (requires --choices)")
    p.add_argument("--timeout-min", type=int, default=DEFAULT_TIMEOUT_MIN)
    p.add_argument("--thread", help="Thread ID to post in (default: $C3R_AGENT_THREAD_ID or main channel)")
    args = p.parse_args()

    if args.multi and not args.choices:
        p.error("--multi requires --choices")

    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    user_id = os.environ.get("DISCORD_USER_ID")
    if not (token and channel_id and user_id):
        print("[ask_human] Missing DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID / DISCORD_USER_ID", file=sys.stderr)
        return 2

    # Posts land in the agent's thread when available, else the main channel.
    target_id = args.thread or os.environ.get("C3R_AGENT_THREAD_ID") or channel_id

    deadline = time.time() + args.timeout_min * 60
    if args.choices:
        answer = choice_mode(token, target_id, user_id, args.question, args.choices, args.multi, deadline)
    else:
        answer = free_text(token, target_id, user_id, args.question, deadline)

    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
