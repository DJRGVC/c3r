#!/usr/bin/env python3
"""
notify.py — Fire-and-forget Discord message sender.

Usage:
  notify.py "message text"                         # posts in main channel
  notify.py --thread THREAD_ID "message text"      # posts in a thread
  notify.py --mention "message text"               # @mentions the configured user

Returns the posted message ID on stdout.
Pure stdlib.
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.error, urllib.request

API = "https://discord.com/api/v10"

def post(token: str, target_id: str, content: str) -> str:
    req = urllib.request.Request(
        f"{API}/channels/{target_id}/messages",
        data=json.dumps({"content": content, "allowed_mentions": {"parse": ["users"]}}).encode(),
        method="POST",
    )
    req.add_header("Authorization", f"Bot {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "c3r-notify (0.1)")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["id"]
    except urllib.error.HTTPError as e:
        print(f"[notify] HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("content")
    p.add_argument("--thread", help="Thread ID to post in (default: main channel)")
    p.add_argument("--mention", action="store_true", help="Prefix with <@USER_ID>")
    args = p.parse_args()

    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel = os.environ.get("DISCORD_CHANNEL_ID")
    user = os.environ.get("DISCORD_USER_ID")
    if not (token and channel):
        print("[notify] missing DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID", file=sys.stderr)
        return 2

    target = args.thread or channel
    content = args.content
    if args.mention and user:
        content = f"<@{user}> {content}"

    print(post(token, target, content))
    return 0

if __name__ == "__main__":
    sys.exit(main())
