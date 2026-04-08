# c3r — Setup Guide

This walks you through installing c3r, creating a Discord bot, and wiring
c3r into a target project repo. End-to-end setup is ~10 minutes if you
already use Firefox + claude.ai.

## 1. Install

```bash
git clone https://github.com/DJRGVC/c3r ~/Research/c3r
~/Research/c3r/c3r install
```

`c3r install` symlinks into `~/.local/bin/c3r`. If that isn't on your PATH,
the installer prints the line to add to your shell rc.

Verify:

```bash
c3r --version
# c3r version 0.3.0 (ea4d5c6)
#   installed at: /home/<you>/Research/c3r
#   config:       /home/<you>/.config/c3r/config.env
```

### Dependencies

- `python3` ≥ 3.9 (stdlib only — no pip installs needed)
- `git` with worktree support (any modern version)
- `tmux`
- `flock` (from `util-linux`, present on every modern Linux)
- `setsid` (from `util-linux` — needed for process-group SIGKILL on iter timeout)
- `claude` — the [Claude Code](https://docs.claude.com/en/docs/claude-code) CLI,
  logged in (`claude --version` succeeds)
- **Firefox** (recommended) — c3r reads claude.ai cookies directly from
  Firefox's SQLite store for live usage tracking. Without Firefox you can
  still use c3r but live usage panels will require manual cookie pasting
  via `c3r usage-auth`.

Run `c3r doctor` to verify all dependencies + Discord reachability + live
usage tracking in one shot.

## 2. Create the Discord bot

c3r uses Discord as the human-in-the-loop interface (one thread per agent,
one pinned status board, mobile notifications).

### Create the application

1. https://discord.com/developers/applications → **New Application**
2. Sidebar → **Bot** → **Add Bot** → copy the bot token (you'll paste it
   into the wizard in step 4)
3. Sidebar → **Bot** → scroll to **Privileged Gateway Intents** →
   enable **MESSAGE CONTENT INTENT** → **Save Changes**.
   ⚠ Without this, your Discord thread replies will arrive with empty
   content and the listener will silently drop them.
4. Sidebar → **OAuth2** → **URL Generator**:
   - Scopes: `bot`
   - Bot permissions:
     - View Channel
     - Send Messages
     - Create Public Threads
     - Send Messages in Threads
     - Read Message History
     - Add Reactions
     - **Manage Threads** (so c3r can delete sub-agent threads on kill)
     - **Manage Messages** (so c3r can pin the status board)
5. Open the generated URL → invite the bot to your server.

### Create a dedicated channel

**Do not use `#general` or an existing channel.** Each project gets its own
channel that the bot fully owns:

1. In your Discord server: right-click a category → **Create Channel**
2. Name it `#c3r-yourproject`
3. Make it **private** or restrict access to yourself
4. **Right-click the channel → Edit Channel → Permissions** → add the bot
   as a member with all of the permissions above. Now the bot is scoped
   to this single channel and cannot read or write anywhere else.

### Grab the IDs

In Discord: **Settings → Advanced → Developer Mode** ON. Then:

- Right-click the c3r channel → **Copy Channel ID**
- Right-click your own username → **Copy User ID**

You'll paste both into the wizard in step 4.

## 3. (Optional) sign in to claude.ai in Firefox

If you have Firefox installed, just visit https://claude.ai/settings/usage
once and sign in. That's it — c3r will automatically read the resulting
session cookies on demand and show your real 5h/7d/per-model usage % in
`c3r watch`. The browser auto-refreshes the cookies whenever you visit any
claude.ai page, so usage stays live indefinitely with zero manual refresh.

If you only use Chrome/Chromium, you'll need to grab cookies manually via
`c3r usage-auth` (paste a curl from devtools — see step 9).

## 4. Initialize a project

```bash
cd ~/Research/YourProject
c3r init
```

The wizard prompts you in this order:

1. **Project name** — defaults to the repo's directory name (e.g. `quadrujuggle`)
2. **Number of agents** — typically 2 (you can spawn more later via `c3r spawn`)
3. **Per agent**:
   - name (no spaces — must be a valid git branch component)
   - role template (`generic` | `literature` | `coding` | `writing` | `custom`)
   - model (`sonnet` | `opus` | `haiku`; defaults to sonnet)
   - one-sentence focus
4. **GPU lock mode** — `serial` (flock-based, recommended for single-GPU
   boxes) or `none`
5. **`max_agents` cap** — global cap including children, default 4
6. **Base branch** — default `c3r/<project>`, forked off `main`
7. **Project env activation** — bash command sourced at the start of every
   iteration. Example: `source /path/to/venv/bin/activate && export WANDB_API_KEY=...`
8. **Discord credentials** — bot token (input is **silent**, doesn't echo
   to terminal or shell history), channel ID, your user ID
9. **Discord smoke test** — bot posts a free-text question + an MCQ poll
   and waits for you to reply. **If this fails, stop and fix bot
   permissions before continuing** — you don't want to discover broken
   permissions after launching agents.
10. **Live usage smoke test** — c3r reads claude.ai cookies from Firefox
    and verifies the live endpoint returns valid data. Reports pass/fail.
11. **Seed `fix_plan.md`** — opens each agent's `fix_plan.md` in `$EDITOR`
    so you can paste in starting tasks. Skip with `n` and edit later.

### What it creates on disk

```
<your-target-repo>/
  .c3r/
    state.json                       single source of truth (agents, threads, cap, paused)
  scripts/c3r → ~/Research/c3r/bin   symlinked tools agents call
  c3r/<project> branch               dedicated base branch (main never touched)

(sibling worktrees next to the repo)
<parent>/<repo>-<agent-name>/        on branch agent/<name>
  .c3r/
    PROMPT.md                        non-negotiable rules + role template
    fix_plan.md                      experiment queue you seeded
    RESEARCH_LOG.md                  empty, agents append per iteration
    INBOX.md                         empty
    INBOX_ARCHIVE.md                 empty
    SIBLINGS.md                      auto-regenerated each iteration
    agent.conf                       model, cooldown, fail cap, iter timeout
    env.sh                           your project env activation
  .claude/
    settings.json                    sandbox PreToolUse hook
```

And in Discord:
- A pinned **status board message** with the agent tree
- One **public thread per agent** named `<agent> · <focus>`

### What goes into `~/.config/c3r/config.env`

This is the only place credentials live (chmod 600, owner-only):

```
export DISCORD_BOT_TOKEN="..."
export DISCORD_CHANNEL_ID="..."
export DISCORD_USER_ID="..."
export CLAUDE_AI_SESSION_KEY="..."     # auto-populated from Firefox if available
export CLAUDE_AI_CF_CLEARANCE="..."    # auto-populated, refreshed periodically
export CLAUDE_AI_CF_BM="..."           # auto-populated
export CLAUDE_AI_ORG_UUID="..."        # auto-populated
```

## 5. Launch

```bash
c3r launch
```

This spins up a tmux session with:
- One window per agent running `bin/agent_loop.sh`
- A `logs` window tailing every agent's `RESEARCH_LOG.md`
- A `listen` window running the Discord ↔ INBOX bridge + auto-refreshing
  the status board every 60 seconds

```bash
c3r attach           # attach to the running session (or: c3r a)
```

Inside tmux:
- `Ctrl-b <n>` → switch to window n (0=first agent, last=listen)
- `Ctrl-b w` → interactive window picker
- `Ctrl-b d` → **detach** (leaves agents running) — never use Ctrl-C

## 6. Watch

```bash
c3r watch          # default 1s refresh, q to quit (or: c3r w)
```

What you see (top to bottom):

```
c3r v0.3.0 · QuadruJuggle [running]   gpu_lock=serial  refresh=1s  q=quit
plan: max-20x  ·  5h:   8%  ·  7d:  41%  ·  7d-sonnet:  18%
  5h window resets in 16h00m  ·  source: claude.ai (live)
────────────────────────────────────────────────────────────
agents: 3/4 active  (1 stopped)
  AGENT              STATUS   MODEL      ITER    CTX%  LAST     FAIL
● policy             running  opus       #18      14%  5s ago      0
  └─ lit-portela     running  sonnet     #3        7%  12s ago     0
● perception         idle     sonnet     #8        9%  22s ago     0
────────────────────────────────────────────────────────────
INBOX  (last 3 · 📬 unread · ✉ read+responded)
  ✉ read    →policy     2026-04-08 19:34 UTC  from Daniel G
      msg:  switch to the Forrai 2023 sigma curriculum next
      resp: bumping fix_plan #4 to top; commit within this iter
────────────────────────────────────────────────────────────
policy:
  iter_018 — Sigma curriculum implementation against pi1
  Result: ...
perception:
  iter_008 — D435i camera mount + RGB+depth render verified
  Result: ...
```

If a c3r update is available, the header shows `↑ N update(s) — c3r update`.

## 7. Interact

### From your phone (Discord)

- **Talk to a specific agent**: reply inside that agent's thread. The
  listener picks it up within ~4 seconds, appends to the agent's `INBOX.md`,
  and reacts ✅. The agent reads INBOX at the start of its next iteration
  and posts a response back in the thread.
- **Pause / resume all** (cooperative — current iter finishes):
  `!c3r pause` / `!c3r resume`
- **Bump the status board** to the bottom of the channel: `!c3r status`
- **Ping a specific agent from the main channel**: `!c3r ping <agent> <message>`
- **List commands**: `!c3r help`

### From your laptop (CLI)

```bash
c3r status                       # text snapshot + nudge Discord board
c3r logs                         # tail every agent's RESEARCH_LOG.md
c3r logs policy                  # tail just one
c3r ping policy "switch to exp_043"
c3r pause / c3r resume           # cooperative
c3r stop                         # hard kill the tmux session (interrupts in-flight work)
c3r ask "test" --choices a b c   # send yourself a Discord question
```

## 8. Sub-agents (agent hierarchy)

Any running agent can spawn its own sub-agents for bounded sub-tasks. From
inside an agent's iteration:

```bash
$C3R_BIN/c3r spawn lit-search literature \
    "read and summarize the Forrai 2023 paper" --max-iters 10
```

This:
1. Checks the project's `max_agents` cap (only counts active agents)
2. Creates a new git worktree forked off the c3r base branch
3. Seeds `.c3r/` with PROMPT, env.sh (inherited), agent.conf with `MAX_ITERATIONS=10`
4. Creates a Discord thread titled `↳ lit-search · read and summarize…`
5. Adds a tmux window running the agent loop
6. Updates the status board

Sub-agents:
- Auto-fill `parent` from the spawning agent's `$C3R_AGENT_NAME` env
- Default to a 20-iteration budget (override via `--max-iters`)
- Self-kill on hitting the budget
- Are visible to their parent in `SIBLINGS.md` under a `## YOUR CHILDREN` section

The parent agent is told (via PROMPT) to manage children proactively: kill
when the task is done, kill when stale (>2h since last iter), kill when
failing. **Forgotten children are a known failure mode** and the iteration
budget is the safety net.

You can kill any agent yourself:

```bash
c3r kill <agent>      # non-destructive (preserves worktree + branch)
c3r reset <agent>     # destructive (deletes worktree + branch)
```

`c3r kill` cascades to descendants. Sub-agent threads are deleted from
Discord; top-level agent threads are preserved.

## 9. Live Claude usage tracking

c3r shows the same numbers as your `claude.ai/settings/usage` page in `c3r
watch`. The setup:

**If you use Firefox**: nothing to do. c3r reads cookies directly from
`~/snap/firefox/.../cookies.sqlite` (or your standard Firefox profile path)
on every poll. The browser auto-refreshes cookies whenever you view any
claude.ai page, so as long as you visit claude.ai daily, the data stays
fresh forever.

**If you use Chrome or another browser** (or Firefox auto-detect failed):

```bash
c3r usage-auth
```

This prompts you to paste a curl from your browser's devtools. Steps:

1. Open https://claude.ai/settings/usage
2. F12 → **Network** → reload the page
3. Find the request to `/api/organizations/<uuid>/usage`
4. Right-click → **Copy → Copy as cURL**
5. Paste the entire curl into the `c3r usage-auth` prompt, then press Enter
   on a blank line

The script parses out `sessionKey`, `cf_clearance`, `__cf_bm`, and the
org UUID; saves them to `~/.config/c3r/config.env`; and smoke-tests the
endpoint to confirm it works.

`cf_clearance` expires in hours-to-days. If you don't have Firefox to
auto-refresh, you'll need to re-run `c3r usage-auth` periodically when the
watch dashboard shows `⚠ usage: HTTP 403`.

### Plan tier

The plan (Pro / Max 5x / Max 20x) is auto-detected via the live API at
`api.anthropic.com/api/oauth/account` (the local credentials file becomes
stale on plan upgrades; c3r walks all org memberships and picks the highest
tier). Cached for an hour.

## 10. When to ping, when not to

PROMPT.md tells agents to ping you proactively in these cases:
- Environment / binary failure (don't retry blindly, ask)
- Permission denied on a path the agent needs
- `fix_plan.md` exhausted (needs direction)
- 3 consecutive failed iterations
- Architectural decisions affecting main-branch code
- Sibling handoff stuck after 3 of their iterations

Soft `notify.py` (no reply needed): milestones, unexpected findings,
starting long tasks, sibling handoff acknowledgments.

**Budget**: at most 1 blocking `ask_human.py` per hour. `notify.py` calls
are unlimited.

Alerts you'll automatically receive:
- **Context % at 25/50/75/100%** of the 1M token window — 75% and 100%
  @mention you
- **Three consecutive failed iterations** — @mention
- **Circuit breaker tripped** (5 failures) — @mention, agent auto-paused
- **Quota error detected** — agent auto-pauses with reset timestamp,
  auto-resumes when window expires
- **`ask_human.py` timeout** — agent posts its fallback decision in the
  thread so you see what it chose

## 11. Pause, resume, stop, upgrade

```bash
c3r pause           # cooperative — current iter finishes, then sleeps
c3r resume          # clear pause flag
c3r stop            # HARD kill tmux session (interrupts in-flight work)
c3r upgrade         # in-place upgrade (see below)
```

`c3r pause` is non-destructive. Pause now, resume tomorrow, next week —
nothing is lost. The flag file lives at `<worktree>/.c3r/PAUSED` and is
checked between iterations. In-flight training runs finish cleanly first.

## 12. Upgrading c3r in place

When new c3r features ship, refresh an existing project with:

```bash
c3r upgrade
```

This is a single command that:
1. `git pull --ff-only` in `~/Research/c3r`
2. **Cooperative pause** — touches PAUSED flag and waits up to 90s for
   in-flight iterations to finish naturally
3. `tmux kill-session` (now safe — no in-flight work)
4. **Re-renders `PROMPT.md`** in every agent worktree from the latest
   template (preserves the agent's name, role, focus, and existing
   `RESEARCH_LOG.md` / `fix_plan.md` / commits — only the rules section
   updates)
5. Appends `ITERATION_TIMEOUT_SEC=5400` to each `agent.conf` if missing
6. Seeds `.claude/settings.json` (sandbox hook) if missing or stale
7. Clears the pause flag
8. Relaunches tmux

Idempotent. Safe to run while agents are mid-iteration. **For long
training iterations** (>90s), `c3r pause` manually first and wait for
agents to actually pause before running `c3r upgrade` so no training is
lost.

c3r itself periodically checks for upstream updates (every 6 hours, with
caching). When a new version is available, `c3r doctor` warns you and
`c3r watch` shows `↑ N update(s) — c3r update` in the header.

## 13. What to do when things go wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| Smoke test fails at init | Wrong token, bot not in channel, missing intent | Verify bot is in channel and has Message Content Intent enabled |
| Discord listener stops | Network or token issue | `c3r stop && c3r launch` |
| Agents aren't committing | Merge conflicts in worktree | `cd <worktree> && git status` |
| GPU OOM | Two agents launched training outside `gpu_lock.sh` | Confirm both `PROMPT.md` use `$C3R_BIN/gpu_lock.sh` |
| Agent loops without progress | Bad fix_plan or PROMPT | `c3r pause`, inspect `RESEARCH_LOG.md`, edit, `c3r resume` |
| Watch shows `⚠ usage: HTTP 403` | claude.ai cookies expired | Visit claude.ai in Firefox once, OR `c3r usage-auth` |
| Sub-agent thread not deleted on kill | Bot lacks Manage Threads | Grant Manage Threads on the channel |
| Status board not pinned | Bot lacks Manage Messages | Grant Manage Messages on the channel |
| Context % stuck at 0% | (was a bug; fixed in v0.3.0) | `c3r upgrade` |
| Watch shows wrong plan | Stale `~/.claude/.credentials.json` from before plan upgrade | c3r already auto-detects from live API; restart watch |

## 14. Privacy & credential safety

c3r stores all credentials locally and only transmits them to the official
endpoints they belong to:

| Credential | Lives in | Sent only to |
|---|---|---|
| Discord bot token | `~/.config/c3r/config.env` (chmod 600) | `discord.com/api/` |
| claude.ai cookies | Live: Firefox SQLite. Cached: `~/.config/c3r/config.env` | `claude.ai/api/organizations/<your-uuid>/usage` |
| Anthropic OAuth token | `~/.claude/.credentials.json` (Claude Code, chmod 600) | `api.anthropic.com/api/oauth/account` (plan auto-detect) |

Hardening details:
- The init wizard uses **silent input** (`read -rsp`) for the bot token.
  It never echoes to the terminal and never lands in shell history.
- Tmux subprocesses **source `config.env`** (set -a; .) instead of having
  tokens on the bash command line, so `ps -ef` cannot leak credentials to
  other local users.
- The bundled `.gitignore` excludes `config.env`, `*credentials*`,
  `*cookies*`, `state.json` so credentials cannot accidentally land in git.
- c3r does not send any data to the c3r repo or any third-party telemetry
  endpoint. Errors don't include credential bytes.

## 15. Repo philosophy

c3r is **project-agnostic infrastructure**. Project-specific pieces (reward
functions, training commands, metric parsing) live in the target repo, not
in c3r. The only thing you edit in c3r itself is the PROMPT templates —
and only when improvements are generic enough to apply to the next project
too.
