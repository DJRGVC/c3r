#!/usr/bin/env python3
"""
siblings_snapshot.py — regenerate .c3r/SIBLINGS.md for one agent.

Called by agent_loop.sh at the start of every iteration. Produces a concise,
fresh snapshot of what every OTHER agent in the project has been doing, so
the calling agent can coordinate without manual git archaeology.

Per sibling, the snapshot includes:
  - role, focus, status, last iter timestamp
  - last 5 commits on their branch (since divergence from the c3r base branch)
  - list of files they've modified relative to the base branch
  - ready-to-paste `git show <branch>:<file>` commands for the top N files

Usage: siblings_snapshot.py <state.json> <my_agent_name>
"""
from __future__ import annotations
import json, os, subprocess, sys
from datetime import datetime, timezone

def run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False).stdout
    except Exception as e:
        return f"(error: {e})"

def main() -> int:
    if len(sys.argv) != 3:
        print("usage: siblings_snapshot.py <state.json> <my_agent_name>", file=sys.stderr)
        return 2
    state_path, me_name = sys.argv[1:]
    state = json.load(open(state_path))
    me = next((a for a in state["agents"] if a["name"] == me_name), None)
    if not me:
        print(f"no such agent: {me_name}", file=sys.stderr); return 1

    siblings = [a for a in state["agents"] if a["name"] != me_name]
    project = state.get("project", "?")
    base_branch = f"c3r/{project}"  # conventional c3r base branch
    repo = me["worktree"]  # run git in my own worktree

    lines = [
        f"# SIBLINGS — auto-regenerated at the start of each iteration",
        f"",
        f"This file is your snapshot of what every OTHER agent in this project",
        f"has been doing. Use it at the top of every iteration (after reading",
        f"INBOX.md) to stay coordinated.",
        f"",
        f"**To actually read a file from a sibling's branch** (without",
        f"checking it out — they're on separate branches to avoid conflicts):",
        f"```",
        f"git show agent/<sibling-name>:path/to/file",
        f"```",
        f"",
        f"**To see what a sibling has changed since you last looked:**",
        f"```",
        f"git log agent/<sibling-name> --since='1 hour ago' --name-status",
        f"git diff HEAD agent/<sibling-name> -- path/",
        f"```",
        f"",
        f"**To push a handoff file to siblings:** commit it on your own branch",
        f"and reference it in your Discord thread or in your next log entry.",
        f"Siblings will see it in their next SIBLINGS.md refresh.",
        f"",
        f"---",
        f"",
    ]

    if not siblings:
        lines.append("_(no siblings in this project)_")
    else:
        # Ensure we have fresh refs — cheap, local only
        run(["git", "fetch", "--all", "--quiet"], cwd=repo)

        for sib in siblings:
            sib_branch = sib["branch"]
            lines.append(f"## {sib['name']}")
            lines.append(f"- **role**: {sib.get('role','?')}")
            lines.append(f"- **focus**: {sib.get('focus','(none)')}")
            lines.append(f"- **status**: {sib.get('status','?')} · iter #{sib.get('last_iter',0)} · ctx {sib.get('last_context_pct',0)}%")
            ts = sib.get("last_iter_ts")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
                    rel = f"{secs}s ago" if secs<60 else f"{secs//60}m ago" if secs<3600 else f"{secs//3600}h ago"
                    lines.append(f"- **last iter**: {rel}")
                except Exception: pass
            if sib.get("parent"):
                lines.append(f"- **parent**: {sib['parent']} (this is a sub-agent)")
            lines.append("")

            # Recent commits on the sibling's branch
            log = run(
                ["git", "log", sib_branch, "--oneline", "-n", "5", "--no-decorate"],
                cwd=repo,
            ).strip()
            lines.append(f"### Recent commits on `{sib_branch}`")
            lines.append("```")
            lines.append(log if log else "(no commits yet)")
            lines.append("```")

            # Files modified on this sibling's branch relative to the base branch
            # Falls back to HEAD if base branch doesn't exist
            base_ref = base_branch
            base_check = run(["git", "rev-parse", "--verify", base_ref], cwd=repo).strip()
            if not base_check:
                base_ref = "HEAD"
            diff_files = run(
                ["git", "diff", "--name-only", base_ref + "..." + sib_branch],
                cwd=repo,
            ).strip()
            files = [f for f in diff_files.splitlines() if f]
            lines.append(f"### Files modified on `{sib_branch}` (relative to `{base_ref}`)")
            if not files:
                lines.append("_(none)_")
            else:
                lines.append("```")
                for f in files[:30]:
                    lines.append(f)
                if len(files) > 30:
                    lines.append(f"... and {len(files) - 30} more")
                lines.append("```")
                lines.append(f"### Read one with:")
                lines.append("```")
                for f in files[:5]:
                    lines.append(f"git show {sib_branch}:{f}")
                lines.append("```")
            lines.append("")

    out_path = os.path.join(me["worktree"], ".c3r/SIBLINGS.md")
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
