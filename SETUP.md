# c3r — Setup Guide

This walks you through installing c3r, creating a Discord bot, and wiring
c3r into a target project repo.

## 1. Install

```bash
git clone https://github.com/DJRGVC/c3r ~/Research/c3r
~/Research/c3r/c3r install
# or put ~/Research/c3r on your PATH directly
```

`c3r install` symlinks into `~/.local/bin/c3r`. If that isn't on your PATH,
the installer prints the line to add to your shell rc.

### Dependencies

All of these should already be installed on a typical dev machine:
- `python3` (>= 3.9, stdlib only)
- `git` (with worktree support — anything modern)
- `tmux`
- `flock` (from util-linux)
- `claude` — the Claude Code CLI, logged in (`claude --version` succeeds)

Run `c3r doctor` to verify.

## 2. Create a dedicated Discord channel

**Do not use `#general` or an existing channel.** The bot should live in a
channel it fully owns so:
- Its messages don't clutter other conversations
- Permissions are locked down to one channel
- The status board stays findable (pinned at the top of the channel)

### Create the channel

In your Discord server:
1. Right-click a category → **Create Channel**
2. Name it something like `#c3r-yourproject`
3. Make it **private** or restrict access to yourself (Settings → Permissions)

### Create the bot

1. Go to https://discord.com/developers/applications → **New Application**
2. Sidebar → **Bot** → **Add Bot** → copy the bot token
3. Sidebar → **Bot** → scroll to **Privileged Gateway Intents** →
   enable **Message Content Intent** → **Save Changes**.
   ⚠ Without this, your Discord thread replies will arrive with empty content
   and the listener will silently drop them.
4. Sidebar → **OAuth2** → **URL Generator**:
   - Scopes: `bot`
   - Bot permissions:
     - View Channel
     - Send Messages
     - Create Public Threads
     - Send Messages in Threads
     - Read Message History
     - Add Reactions
     - Manage Threads   (needed so c3r can delete sub-agent threads on kill)
4. Open the generated URL → invite the bot to your server
5. In your server's channel settings, **restrict the bot to the c3r channel only**
   (remove its access from every other channel). This is a one-time click in
   the channel's Permissions tab.

### Privacy & credential safety

c3r stores all credentials locally and never transmits them to anywhere
other than the official endpoints they belong to:

- **Discord bot token** → `~/.config/c3r/config.env` (chmod 600), only sent
  in headers to `discord.com/api/`
- **claude.ai cookies** → `~/.config/c3r/config.env` (chmod 600), read live
  from your local Firefox cookie store, only sent in headers to
  `claude.ai/api/organizations/<your-uuid>/usage`
- **Anthropic OAuth token** → not c3r-managed; lives in
  `~/.claude/.credentials.json` (chmod 600 by Claude Code), used only to hit
  `api.anthropic.com/api/oauth/account` for plan-tier auto-detection

c3r writes to **two** files only:
- `~/.config/c3r/config.env` — chmod 600, owner-only
- `<your-target-repo>/.c3r/state.json` — non-secret, but contains agent
  metadata; gitignored if you use the bundled `.gitignore`

c3r does **not**:
- Send any data to the c3r repo or any third-party telemetry endpoint
- Log credentials to stdout/stderr (errors redact tokens)
- Commit credentials to git (the bundled `.gitignore` excludes
  `config.env`, `*credentials*`, `*cookies*`, and `.c3r/state.json`)

### Grab the IDs

In Discord: **Settings → Advanced → Developer Mode** ON. Then:
- Right-click your c3r channel → **Copy Channel ID**
- Right-click your own username → **Copy User ID**

## 3. Initialize a project

```bash
cd ~/Research/YourProject
c3r init
```

The wizard asks for:
- **Project name** (for tmux session and Discord board title)
- **Number of agents** and for each: name, role template, model, focus
- **GPU lock mode** (`serial` or `none`)
- **Discord credentials** (token / channel ID / user ID) — saved once to
  `~/.config/c3r/config.env` (chmod 600)
- **Smoke test** — bot posts a free-text question + an MCQ poll and waits
  for your reply. If this fails, don't continue — fix bot permissions first.
- **Starting tasks** (optional) for each agent's fix_plan.md

What it creates:
- `<parent>/YourProject-<agent>` git worktrees, one per agent, on branches `agent/<name>`
- `.c3r/state.json` in the main repo (the single source of truth for agents/threads/status)
- `.c3r/{PROMPT,fix_plan,RESEARCH_LOG,INBOX}.md` + `agent.conf` in each worktree
- `scripts/c3r` symlink in the main repo pointing at c3r's `bin/` dir
- A **pinned status board message** in your Discord channel, with one
  thread per agent created off it

## 4. Launch

```bash
c3r launch
tmux attach -t c3r-YourProject
```

Windows in the session:
- One per agent, running `bin/agent_loop.sh`
- `logs` — tails each agent's `RESEARCH_LOG.md`
- `listen` — runs the Discord → INBOX listener

Detach with `Ctrl-b d`. Agents keep running in the background.

## 5. Interact

### From your phone (Discord)

- **Talk to a specific agent**: reply inside that agent's thread. The
  listener sees new messages and appends them to the agent's `INBOX.md`
  (with a ✓ reaction to ack). The agent reads INBOX at the start of its
  next iteration.
- **Pause / resume all**: type `!c3r pause` or `!c3r resume` in the main
  channel.
- **Force the status board back to the bottom**: `!c3r status`.
- **Message a specific agent from the main channel**: `!c3r ping policy
  "try the Portela 2025 sigma curriculum"`.

### From your laptop (CLI)

```bash
c3r status                       # local dashboard + nudge Discord board
c3r logs policy                  # tail one agent's log
c3r ping policy "switch to exp_043 config"
c3r pause                         # pause all agents
c3r resume
c3r reset literature              # destructively remove an agent
```

## 6. Model default is Sonnet, not Opus

Each agent's `.c3r/agent.conf` sets `AGENT_MODEL="claude-sonnet-4-6"` by
default. Reason: on Max 5x ($100/mo), two continuous agents on Opus would
burn the weekly Opus quota in a day. Sonnet is genuinely strong for the
loop work (read log, propose change, parse results, write log entry), and
Opus is overkill.

If you want one agent on Opus, edit that agent's `agent.conf` and
`c3r stop && c3r launch` to restart.

## 7. When to ping, when not to

Each agent's PROMPT.md includes the rule *"at most 1 ping per hour."*
Agents that are under-pinging (silent for days) usually need their
`fix_plan.md` unblocked via `c3r ping`. Agents that are over-pinging (more
than ~5/day) have a PROMPT.md threshold that's too low — tighten the "when
to call ask_human" section for that agent.

Alerts you will automatically receive:
- **Context % at 25/50/75/100%** of the 200k window per iteration. The 75%
  and 100% alerts @mention you — they mean the agent's working-set
  (RESEARCH_LOG.md + fix_plan.md + PROMPT.md + code reads) is getting too
  large and should be pruned.
- **Three failed iterations in a row** — @mention, investigate.
- **Circuit breaker tripped** (five failures) — agent is auto-paused. Run
  `c3r resume` after fixing.

## 8. What to do when things go wrong

- **Smoke test fails** → wrong token or the bot isn't in the channel. Re-run
  `c3r init` and re-enter credentials. Verify the bot appears in the channel's
  member list.
- **Discord listener stops** → check the `listen` tmux window for errors;
  `c3r stop && c3r launch` to restart.
- **Agents aren't committing** → check for merge conflicts in each worktree;
  `cd <worktree> && git status`.
- **GPU OOM** → you disabled the GPU lock, or two agents launched training
  outside the lock. Check that both PROMPT.md files insist on
  `$C3R_BIN/gpu_lock.sh`.
- **Agent seems stuck in a loop** → the circuit breaker should trip after 5
  failures. If not, `c3r pause`, inspect `.c3r/RESEARCH_LOG.md`, edit the
  PROMPT.md, `c3r resume`.

## 9. Repo philosophy

c3r is **project-agnostic infrastructure**. Project-specific pieces
(reward functions, training commands, metric parsing) live in the target
repo, not here. The only thing you edit in c3r itself is the PROMPT
templates — and only when improvements are generic enough to apply to the
next project too.
