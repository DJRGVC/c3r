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

    # Children: agents whose parent == me (recursively → all descendants)
    def descendants(name):
        out = []
        for a in state["agents"]:
            if a.get("parent") == name:
                out.append(a)
                out.extend(descendants(a["name"]))
        return out
    my_children = descendants(me_name)
    my_child_names = {a["name"] for a in my_children}
    siblings = [a for a in state["agents"]
                if a["name"] != me_name
                and a["name"] not in my_child_names
                and a.get("status") != "stopped"]
    project = state.get("project", "?")
    base_branch = f"c3r/{project}"
    repo = me["worktree"]

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

    # ---- YOUR CHILDREN section (always first when present) ----
    if my_children:
        from datetime import datetime, timezone
        lines.append("## YOUR CHILDREN — agents YOU spawned and YOU must manage")
        lines.append("")
        lines.append("These are sub-agents you spawned (directly or transitively).")
        lines.append("**YOU are responsible for killing them when their task is done,")
        lines.append("they get stuck, or they exceed their useful budget.** Each child")
        lines.append("also has a hard iteration cap and will self-kill at MAX_ITERATIONS,")
        lines.append("but that's a safety net — proactive management is your job.")
        lines.append("")
        for c in my_children:
            status = c.get("status", "?")
            iter_n = c.get("last_iter", 0)
            ts = c.get("last_iter_ts")
            rel = ""
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
                    rel = (f"{secs}s ago" if secs<60 else f"{secs//60}m ago"
                           if secs<3600 else f"{secs//3600}h ago")
                except Exception: pass
            stale = "  ⚠ STALE — consider killing" if rel and "h ago" in rel and int(rel.split("h")[0]) >= 2 else ""
            stopped = "  (already stopped)" if status == "stopped" else ""
            lines.append(f"- **{c['name']}** ({c.get('role','?')}, parent={c.get('parent','?')}) — "
                         f"status={status}, iter=#{iter_n}, last={rel or 'never'}{stale}{stopped}")
            lines.append(f"  Focus: {c.get('focus','(none)')}")
        lines.append("")
        lines.append("**Decision rules** (apply at the top of every iteration):")
        lines.append("1. If a child's last RESEARCH_LOG entry says its task is done, kill it: `$C3R_BIN/c3r kill <name>`")
        lines.append("2. If a child has been stale (no iter for >2 hours), kill it.")
        lines.append("3. If a child's fail_streak ≥ 3 in state.json, investigate or kill it.")
        lines.append("4. Otherwise, leave it running and check again next iteration.")
        lines.append("")
        lines.append("---")
        lines.append("")

    if not siblings:
        lines.append("## SIBLINGS")
        lines.append("")
        lines.append("_(no other active agents in this project)_")
    else:
        lines.append("## SIBLINGS — peers you do NOT manage (other agents' work)")
        lines.append("")
        # Worktrees share the same .git directory, so sibling branch refs
        # are already up to date locally — no fetch needed.
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
