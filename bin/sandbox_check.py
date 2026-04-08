#!/usr/bin/env python3
"""
sandbox_check.py — Claude Code PreToolUse hook that rejects file writes
outside the agent's worktree.

Reads a JSON event from stdin (Claude Code hook protocol) and exits:
  0 = allow
  2 = deny (Claude Code treats non-zero exit as denial)

Hooked on Write / Edit / NotebookEdit. Bash is NOT hooked because shell
commands can reference paths via variables / subshells, making reliable
path extraction brittle. The PROMPT.md rule (`never cd out of
$C3R_WORKTREE`) is the primary defense for Bash; this hook is the
belt-and-suspenders for the Edit/Write path.

Allowed file paths:
  - Anything under $C3R_WORKTREE (the agent's own git worktree)
  - Anything under /tmp (for temp files; clean cleanup is the agent's job)

Denied:
  - Absolute paths outside $C3R_WORKTREE and /tmp
  - Paths that resolve via .. to outside the worktree

Env required: C3R_WORKTREE (absolute path)
"""
from __future__ import annotations
import json, os, sys

def main() -> int:
    wt = os.environ.get("C3R_WORKTREE")
    if not wt:
        # Without C3R_WORKTREE we can't enforce — fail open with a warning.
        print("[sandbox_check] C3R_WORKTREE unset; allowing", file=sys.stderr)
        return 0
    wt = os.path.realpath(wt)

    try:
        event = json.load(sys.stdin)
    except Exception as e:
        print(f"[sandbox_check] could not parse hook input: {e}", file=sys.stderr)
        return 0  # fail open on parse errors

    tool = event.get("tool_name") or event.get("tool") or ""
    tool_input = event.get("tool_input") or event.get("input") or {}
    # Write/Edit use 'file_path'; NotebookEdit uses 'notebook_path'
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not path:
        return 0

    # Resolve relative paths against the worktree (Claude Code usually passes absolute)
    if not os.path.isabs(path):
        path = os.path.join(wt, path)
    real = os.path.realpath(path)

    # Allow list
    if real.startswith(wt + os.sep) or real == wt:
        return 0
    if real.startswith("/tmp/") or real == "/tmp":
        return 0

    # Deny
    msg = (
        f"[sandbox_check] DENIED {tool} to path outside worktree:\n"
        f"  requested: {path}\n"
        f"  resolved:  {real}\n"
        f"  worktree:  {wt}\n"
        f"If you genuinely need to write here, ask the human via ask_human.py "
        f"first — do NOT bypass this by trying another path."
    )
    print(msg, file=sys.stderr)
    return 2

if __name__ == "__main__":
    sys.exit(main())
