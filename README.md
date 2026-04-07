# c3r — Continuous Context Claude Research

Harness for running two Claude Code research agents in parallel on a local RL
project, with Discord as the human-in-the-loop channel and git worktrees +
flock keeping the agents from stepping on each other or the GPU.

See [SETUP.md](SETUP.md) for the full walkthrough.

## Quick start

```bash
# 1. Set Discord env vars (see SETUP.md §2)
export DISCORD_BOT_TOKEN=... DISCORD_CHANNEL_ID=... DISCORD_USER_ID=...

# 2. Smoke-test the bridge
~/Research/c3r/bin/ask_human.py "smoke test"

# 3. Wire into a target repo
~/Research/c3r/init.sh ~/Research/QuadruJuggle policy perception

# 4. Launch
~/Research/c3r/scripts/launch_agents.sh ~/Research/QuadruJuggle policy perception
tmux attach -t c3r
```

Built on top of [ralph-claude-code](https://github.com/frankbria/ralph-claude-code).
