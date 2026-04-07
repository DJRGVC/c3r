# c3r — Continuous Context Claude Research

Run two or more Claude Code research agents in parallel on a local project,
with Discord threads as the human-in-the-loop interface and git worktrees
keeping the agents from stepping on each other.

Project-agnostic. Use it for RL training loops, literature review swarms,
long-running code refactors — anything that benefits from a persistent,
compounding research process.

## Features

- **Multi-agent loop** (1–N agents, one per git worktree) on a minimal
  ~40-line `claude -p` wrapper — no external loop runner dependency
- **Discord thread per agent**: reply inside a thread to message the agent;
  agent questions and alerts land in the same thread
- **Persistent status board** (one pinned Discord message, edited in place)
  showing agent status, current iteration, and context usage
- **Cooperative pause/resume** that never kills in-flight training jobs
- **Per-iteration context % alerts** at 25/50/75/100%
- **GPU lock** (flock) so concurrent agents can't OOM a shared GPU
- **Fully stdlib Python + bash** — no npm, no pip, no open ports

## Quick start

```bash
git clone https://github.com/DJRGVC/c3r ~/Research/c3r
~/Research/c3r/c3r install                   # symlink into ~/.local/bin
c3r init ~/Research/YourProject              # interactive wizard
c3r launch ~/Research/YourProject             # start tmux session
tmux attach -t c3r-YourProject
```

See [SETUP.md](SETUP.md) for the full walkthrough.

## CLI overview

```
c3r install                   Symlink c3r into ~/.local/bin
c3r init [path]               Interactive project setup wizard
c3r doctor                    Verify env, Discord bot, tools
c3r launch [path]             Start the tmux session
c3r stop [path]               Kill the session (non-destructive)
c3r pause [path]              Pause all agents (finishes current iter)
c3r resume [path]             Resume paused agents
c3r status [path]             Local + Discord status snapshot
c3r logs [path] [agent]       Tail RESEARCH_LOG.md
c3r ping [path] agent msg     Message an agent's INBOX
c3r ask "question" [--choices a b c]
c3r reset [path] agent        Delete an agent (destructive)
c3r board (bump|update)       Manage the Discord status board
c3r listen [path]             Foreground Discord listener
c3r update                    git pull c3r itself
c3r help [command]            Overview or per-command detail
```

And in Discord (type in the project channel):
```
!c3r help | status | pause | resume | ping <agent> <msg>
```
To talk to an agent, **just reply in its Discord thread** — no command needed.
