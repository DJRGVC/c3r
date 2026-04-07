# c3r — Continuous Context Claude Research

A minimal harness for running **two Claude Code research agents in parallel** on a
local RL project, with **Discord** as the human-in-the-loop channel and **git
worktrees** + **flock** keeping the agents from stepping on each other or the GPU.

Built on top of [ralph-claude-code](https://github.com/frankbria/ralph-claude-code)
as the loop runner. c3r adds: open-ended-research-friendly config, GPU lockfile,
Discord bridge (free-text + reaction-poll MCQ), worktree orchestration, and a
role-split PROMPT.md pair so the two agents don't redo each other's experiments.

---

## Layout

```
c3r/
  bin/              # generic tools; symlink into each target repo
    ask_human.py
    gpu_lock.sh
  templates/        # copied into each worktree's .ralph/ on init
    PROMPT_policy.md
    PROMPT_perception.md
    fix_plan.md
    RESEARCH_LOG.md
    ralphrc.example
  scripts/          # orchestration
    setup_worktrees.sh
    launch_agents.sh
  init.sh           # one-shot: wire c3r into a target repo
  SETUP.md          # you are here
```

---

## One-time setup

### 1. Install Ralph

```bash
npm install -g ralph-claude-code   # or: pipx / whatever Ralph recommends
```

### 2. Create a Discord bot

1. https://discord.com/developers/applications → **New Application**
2. Sidebar → **Bot** → **Add Bot** → copy token (this is `DISCORD_BOT_TOKEN`)
3. Sidebar → **OAuth2** → **URL Generator** → scopes: `bot`; permissions:
   `Send Messages`, `Read Message History`, `Add Reactions`, `Read Messages/View Channels`
4. Open the generated URL → invite to a server you control (or a new one for this)
5. In Discord, enable Developer Mode (Settings → Advanced → Developer Mode)
6. Right-click the channel you want the bot to post in → **Copy Channel ID**
   → this is `DISCORD_CHANNEL_ID`
7. Right-click your own username → **Copy User ID** → this is `DISCORD_USER_ID`
   (used to filter reactions/messages so only *your* taps count)

Export them in your shell rc:
```bash
export DISCORD_BOT_TOKEN="..."
export DISCORD_CHANNEL_ID="..."
export DISCORD_USER_ID="..."
```

### 3. Smoke-test the Discord bridge

Before anything else, confirm the bridge works standalone:
```bash
~/Research/c3r/bin/ask_human.py "c3r smoke test — reply 'ok'"
# → check Discord, type 'ok', script should print 'ok' and exit

~/Research/c3r/bin/ask_human.py "pick one" --choices "left" "middle" "right"
# → tap 🇦/🇧/🇨 in Discord, script prints the chosen option
```

If this doesn't work, nothing downstream matters — debug here first.

---

## Wiring c3r into a project (e.g. QuadruJuggle)

```bash
~/Research/c3r/init.sh ~/Research/QuadruJuggle policy perception
```

This creates two sibling worktrees:
```
~/Research/QuadruJuggle-policy/      (branch: agent/policy)
~/Research/QuadruJuggle-perception/  (branch: agent/perception)
```

Each worktree gets a seeded `.ralph/` with `PROMPT.md`, `fix_plan.md`,
`RESEARCH_LOG.md`, `.ralphrc`. The `bin/` tools are symlinked into
`<target>/scripts/c3r` so the agents can call them as
`./scripts/c3r/ask_human.py` etc.

Then, inside **each** worktree once:
```bash
cd ~/Research/QuadruJuggle-policy && ralph-enable-ci
cd ~/Research/QuadruJuggle-perception && ralph-enable-ci
```

### Seed the experiment queue

Open each worktree's `.ralph/fix_plan.md` and replace the placeholder queue with
3–5 concrete starting tasks *before* launching. Cold-starting an agent with an
empty queue is how you get it to wander.

---

## Launching

```bash
~/Research/c3r/scripts/launch_agents.sh ~/Research/QuadruJuggle policy perception
tmux attach -t c3r
```

Three tmux windows: `policy`, `perception`, `logs` (tailing both RESEARCH_LOGs).
Detach with `Ctrl-b d`. The agents keep running in the background.

To stop everything:
```bash
tmux kill-session -t c3r
```

---

## Model default: Sonnet 4.6, not Opus

`.ralphrc` sets `CLAUDE_MODEL=claude-sonnet-4-6`. With Max 5x ($100/mo), two
continuous Opus agents will blow the weekly cap in a day. Sonnet is genuinely
strong at this work-loop — reading logs, proposing one-variable changes, parsing
metrics, writing structured journal entries. Reserve Opus for when *you*
manually dive in to debug a stuck problem (`/model opus` inside a session).

---

## Known gotchas

- **Agents will redo each other's experiments on day 1.** The worktree split
  prevents source conflicts, but each agent only sees its own `RESEARCH_LOG.md`.
  Both PROMPT.md files already tell the agents to `git fetch && git log --all
  --oneline -20` at the start of every iteration — but if you still see
  duplication after a day, tighten the scope split further.
- **`ask_human.py` will over-fire on day 1.** New prompts are anxious prompts.
  If you're getting more than ~5 pings/day, tighten the "when to call ask_human"
  section of PROMPT.md — the threshold is wrong, not your tolerance.
- **Discord reaction mode needs 1-on-1-ish channel discipline.** The script
  filters reactions by your `DISCORD_USER_ID`, so other server members tapping
  won't confuse it. But free-text mode will pick up *any* message from you in
  that channel after the question, so don't use the bot's channel for unrelated
  chat while a question is pending.
- **Long training runs hold the GPU lock.** If you need to manually run
  something on the GPU, `tmux kill-session -t c3r` first, or wait for a lull.
- **Ralph is v0.x.** Pin a commit once you have a working setup so an upstream
  bugfix doesn't break your overnight run.

---

## Repo philosophy

c3r is **project-agnostic infrastructure**. Anything project-specific (reward
functions, training commands, metric parsing) lives in the target repo, not
here. The only thing you ever edit in c3r is the PROMPT templates and the
ralphrc defaults — and only when the improvements are generic enough to apply
to the next project too.
