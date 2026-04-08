# c3r — Continuous Context Claude Research

A project-agnostic harness for running multiple Claude Code research agents
in parallel on a local project, with **Discord threads** as the human-in-the-loop
interface, **git worktrees** for per-agent isolation, **agent hierarchy**
(parents spawn and manage sub-agents), and **live usage tracking** that mirrors
your `claude.ai/settings/usage` page.

Project-agnostic. Use it for RL training loops, literature review swarms,
long-running code refactors — anything that benefits from a persistent,
compounding research process.

## Features

- **Multi-agent continuous loop** — N top-level agents (typically 2–4) on a
  minimal `claude -p` wrapper. No npm, no pip, no Ralph, no external loop runner.
- **Agent hierarchy** — any running agent can call `$C3R_BIN/c3r spawn` to
  create a bounded sub-agent. Parent links auto-fill via `$C3R_AGENT_NAME`.
  Sub-agents get a default 20-iteration budget and self-kill on hitting it.
  `c3r kill` cascades to descendants. Permission model prevents agents from
  killing siblings.
- **Discord thread per agent** with descriptive titles (`policy · tune
  reward weights…`, `↳ lit-portela · summarize Forrai 2023…`). Reply inside
  a thread to send the agent an INBOX message; agent responses and alerts
  land in the same thread.
- **Sub-agent thread cleanup** — when a sub-agent is killed, its Discord
  thread is deleted entirely (requires the bot's `Manage Threads` permission).
  Top-level agents keep their threads for history.
- **Persistent status board** — one pinned Discord message edited in place,
  rendering the full agent tree with status, iter count, context %, last-iter
  timestamp, and active-vs-stopped agent count.
- **Live `claude.ai/settings/usage` numbers** in `c3r watch` — reads cookies
  directly from your Firefox cookie store (auto-refreshed by the browser
  whenever you visit any claude.ai page) and queries the same endpoint the
  page uses, returning the exact same percentages: 5h utilization, 7d, per-model
  windows, and reset countdowns. **Zero manual refresh** as long as Firefox
  visits claude.ai daily.
- **Live plan-tier auto-detection** via `api.anthropic.com/api/oauth/account`
  (the local credentials file becomes stale on plan upgrades; we walk all
  organization memberships and pick the highest tier).
- **Cross-branch awareness** — `.c3r/SIBLINGS.md` regenerated at the start of
  every iteration with each sibling's recent commits, modified files, and
  copy-pasteable `git show` commands. Plus a `## YOUR CHILDREN` section so
  parents see their direct descendants with stale-detection.
- **Sandbox enforcement** — Claude Code `PreToolUse` hook in
  `.claude/settings.json` rejects Write/Edit/NotebookEdit to file paths
  outside the agent's worktree (or `/tmp`). Agents cannot accidentally write
  to `~/Downloads`, other agents' worktrees, or your main repo.
- **Cooperative pause/resume** that never kills in-flight iterations.
- **Quota-error auto-pause** — `agent_loop.sh` detects Anthropic rate-limit
  errors, sets `.c3r/PAUSED_QUOTA` with a parsed reset timestamp, posts a
  Discord notification, and auto-resumes when the timestamp expires.
- **Self-compaction protocol** — agents are instructed to compact their own
  `RESEARCH_LOG.md` into a summary + archive when context climbs past 50%
  or the log exceeds 300 lines.
- **Per-iteration context % tracking** including cached prompt tokens (Claude
  Code uses prompt caching heavily; the bulk of context utilization lives in
  `cache_read_input_tokens`, which c3r now correctly counts).
- **Iteration timeout** (default 90 minutes) wraps each `claude -p` call in
  a process-group `setsid` + watchdog so a stuck simulator/training process
  gets SIGKILL'd through the entire subtree, with no orphans holding GPU
  memory.
- **GPU lock** (`flock`) so concurrent agents can't OOM a shared GPU.
- **Circuit breaker** trips after 5 consecutive failures, auto-pauses, and
  @mentions you in the agent's Discord thread.
- **Live dashboard** (`c3r watch`) at 1s refresh showing the full agent
  tree, the last 3 INBOX messages with responses, recent log entries, plus
  the live usage panel.
- **Proactive ping policy** — agents are required to ping you on env failures,
  permission denied, fix_plan exhaustion, 3 consecutive fails, architectural
  decisions, or stuck sibling handoffs. On `ask_human.py` timeout, the agent
  posts its fallback decision back to the thread so you see it on your phone.
- **In-place project upgrade** via `c3r upgrade <path>` — pulls latest c3r,
  cooperatively pauses agents, re-renders `PROMPT.md` from the latest template,
  appends missing `agent.conf` fields, seeds the sandbox hook, relaunches.
  Idempotent. Safe to run while agents are mid-iteration (will wait up to 90s
  for in-flight iters to finish).
- **Fully stdlib Python + bash** — no npm, no pip, no extra deps. Only
  external dependency is the `claude` CLI itself.

## Quick start

**One-line install** (Linux + macOS — Windows: use [WSL2](#windows)):

```bash
curl -fsSL https://raw.githubusercontent.com/DJRGVC/c3r/main/install.sh | bash
```

This clones c3r to `~/.local/share/c3r`, symlinks the CLI into `~/.local/bin/c3r`,
verifies dependencies, and prints next steps. No sudo, nothing outside `$HOME`,
no telemetry.

Then:

```bash
c3r doctor                                  # verify install + dependencies
c3r setup ~/Research/YourProject            # interactive Discord-bot + agent wizard
c3r launch ~/Research/YourProject           # spin up the tmux session
c3r watch  ~/Research/YourProject           # live dashboard
```

See [SETUP.md](SETUP.md) for the full walkthrough.

### Windows

c3r is bash + tmux + flock + setsid + python — POSIX-only. **Use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)**: install Ubuntu in WSL2,
open a WSL terminal, and run the curl installer above. Everything works
identically because WSL2 is a real Linux environment. There is no native
Windows port and there's no plan for one — WSL2 covers the use case.

### Manual install (alternative to curl)

```bash
git clone https://github.com/DJRGVC/c3r ~/Research/c3r
~/Research/c3r/c3r install                  # symlink into ~/.local/bin
```

## CLI

```
SETUP
  c3r install                      Symlink c3r into ~/.local/bin
  c3r init [path]                  Interactive project wizard
  c3r doctor [path]                Verify env, tools, Discord, live usage
  c3r config                       Show saved config (secrets redacted)
  c3r usage-auth                   Refresh claude.ai cookies manually (rare)

RUNNING
  c3r launch [path]                Start tmux session
  c3r attach [path]                Attach to running session (alias: a)
  c3r watch [path] [sec]           Live dashboard (alias: w; default 1s refresh)
  c3r status [path]                Text snapshot + nudge Discord board
  c3r logs [path] [agent]          Tail RESEARCH_LOG.md
  c3r stop [path]                  Hard kill the tmux session
  c3r pause [path]                 Cooperative pause (current iter finishes)
  c3r resume [path]                Resume paused agents
  c3r upgrade [path]               Pull, pause, re-render templates, relaunch

AGENT MANAGEMENT
  c3r spawn [path] NAME ROLE "FOCUS" [--model M] [--max-iters N]
                                    Create a new agent (auto-fills parent
                                    when called from inside another agent)
  c3r kill [path] NAME             Non-destructive stop, cascade to descendants
  c3r reset [path] NAME            Destructive: delete worktree + branch

HUMAN ↔ AGENT
  c3r ping [path] NAME MSG         Send to an agent's INBOX
  c3r ask "q" [--choices a b c]    Send yourself a Discord question
  c3r board [path] bump|update     Manage the persistent status board
  c3r listen [path]                Foreground Discord ↔ INBOX listener

MAINTENANCE
  c3r update                       git pull c3r itself
  c3r upgrade [path]               In-place project upgrade
  c3r uninstall                    Remove ~/.local/bin symlink
  c3r help [command]               Overview or per-command details
```

In Discord, from the project channel:

```
!c3r help | status | pause | resume | ping <agent> <message>
```

And inside any agent's thread, just type a message. The listener auto-ingests
it into that agent's `INBOX.md` and reacts with ✓.

## Architecture

```
your project repo (e.g. ~/Research/YourProject)
├── .c3r/
│   └── state.json             single source of truth: agents, threads,
│                               max_agents, paused state
├── scripts/c3r → c3r/bin      symlinked tools the agents call
├── main, feature branches…    untouched by c3r
└── c3r/<project> branch       dedicated base branch for agent forks

(sibling worktrees live next to the repo)
~/Research/YourProject-policy/        on branch agent/policy (forked off c3r/<project>)
│   .c3r/
│     PROMPT.md                       non-negotiable rules + role template
│     fix_plan.md                     experiment queue (you seed, agents consume)
│     RESEARCH_LOG.md                 append-only log
│     RESEARCH_LOG_ARCHIVE.md         self-compacted older entries
│     SIBLINGS.md                     auto-regen each iter (siblings + YOUR CHILDREN)
│     INBOX.md / INBOX_ARCHIVE.md     human ↔ agent message log
│     agent.conf                      model, cooldown, fail cap, iter timeout
│     env.sh                          project venv/CUDA activation
│     PAUSED                          flag file; presence = pause between iters
│     PAUSED_QUOTA                    quota-driven pause with auto-resume timestamp
│   .claude/
│     settings.json                   sandbox hook (rejects writes outside worktree)
```

## Project environment activation

c3r knows nothing about your project's tooling. You tell it once at init:

```
Activation command (or empty): source /path/to/venv/bin/activate && export WANDB_API_KEY=...
```

That string goes into `.c3r/env.sh` in every worktree and is sourced at the
start of every iteration. Sub-agents spawned via `c3r spawn` inherit the
same `env.sh`. When the project env changes, edit `env.sh` once per worktree
and the next iteration picks it up.

### Weights & Biases

Agents can read run metrics via the wandb Python API (non-blocking, works
for in-progress runs too). Set `WANDB_API_KEY` in `.c3r/env.sh` or run
`wandb login` once outside c3r. The PROMPT template explicitly teaches
the Python API pattern for reading runs.

## Live usage tracking

c3r shows the same numbers as your `claude.ai/settings/usage` page in `c3r
watch`, with **zero manual refresh** as long as you have Firefox installed
and have visited `claude.ai` recently:

```
plan: max-20x  ·  5h:   8%  ·  7d:  41%  ·  7d-sonnet:  18%
  5h window resets in 16h00m  ·  source: claude.ai (live)
```

How it works: `bin/claude_usage.py` reads claude.ai cookies directly from
your Firefox SQLite cookie store (read-only mode, safe with running Firefox)
and queries `claude.ai/api/organizations/<uuid>/usage`. The cookies are
auto-refreshed by Firefox itself whenever you view any claude.ai page, so
the data stays fresh without intervention.

If Firefox isn't your browser, run `c3r usage-auth` once to paste a curl
from Chrome devtools manually. Cookies persist in `~/.config/c3r/config.env`
(chmod 600) and need refreshing only when they expire (hours-to-days,
depending on Cloudflare).

## Safety properties

1. **Sandbox** — PreToolUse hook physically rejects Write/Edit/NotebookEdit
   to file paths outside the worktree (or `/tmp`). Agents cannot write to
   `~/Downloads`, other worktrees, or your main repo.
2. **Base branch isolation** — agents never touch `main`. They fork from
   `c3r/<project>` → `agent/<name>` and commit only there. You merge back
   manually.
3. **GPU lock** — `gpu_lock.sh` uses `flock` so two agents can't OOM the GPU.
4. **Iteration timeout (90 min default)** — `setsid` + process-group
   SIGKILL on the watchdog so any stuck simulator gets cleanly killed.
5. **Quota-error auto-pause** — quota errors don't count toward fail_streak;
   agents pause until the rate limit window resets, then auto-resume.
6. **Circuit breaker** — 5 consecutive failures auto-pause + @mention.
   Counter resets to 0 on the breaker so the dashboard reflects current state.
7. **`max_agents` cap** — global, asked at init. Spawn refuses cleanly when
   full. Stopped agents don't count against the cap.
8. **Sub-agent iteration budget** — default 20 iters; agent self-kills at the
   budget so a forgotten child doesn't burn quota indefinitely.
9. **Permission model for kill** — an agent may only kill itself or
   descendants in its own subtree.
10. **`--disallowedTools Task`** at the CLI level — agents physically cannot
    use Claude Code's built-in Task tool to spawn invisible sub-agents.
    All sub-agent spawning must go through `c3r spawn`.
11. **Sonnet default** — agents run on Sonnet 4.6 unless flipped to Opus
    in their `agent.conf`. Avoids burning weekly Opus quota by accident.
12. **Self-compaction protocol** — agents prune their own `RESEARCH_LOG.md`
    when context % crosses 50% or the log exceeds 300 lines.

## Credential safety

c3r stores all credentials locally and only transmits them to the official
endpoints they belong to:

- **Discord bot token** → `~/.config/c3r/config.env` (chmod 600), only sent
  in headers to `discord.com/api/`. **Sourced into agent processes via
  `set -a; . config.env; set +a`** so it never appears on a command line
  visible to `ps -ef`.
- **claude.ai cookies** (sessionKey, cf_clearance, __cf_bm) → read live from
  the Firefox SQLite store at request time, persisted to
  `~/.config/c3r/config.env` as a fallback. Only sent to
  `claude.ai/api/organizations/<your-uuid>/usage`.
- **Anthropic OAuth token** → not c3r-managed; lives in
  `~/.claude/.credentials.json` (chmod 600 by Claude Code). Used only to
  hit `api.anthropic.com/api/oauth/account` for plan-tier auto-detection.

The init wizard uses **silent input** (`read -rsp`) for the bot token so it
never echoes to the terminal or lands in shell history.

c3r does **not**:
- Send any data to the c3r repo or any third-party telemetry endpoint
- Log credentials to stdout/stderr (errors redact tokens)
- Commit credentials to git (the bundled `.gitignore` excludes `config.env`,
  `*credentials*`, `*cookies*`, and `state.json`)
- Put credentials on tmux command lines (sourced via config.env in subshells)

## Proactive communication

Agents are explicitly instructed to reach out on their own initiative.
Mandatory ping triggers:

- Environment / binary failure (don't retry blindly, ask)
- Permission denied on a path the agent needs
- `fix_plan.md` exhausted (needs direction)
- 3 consecutive failed iterations (before circuit breaker hits 5)
- Architectural decisions affecting main-branch code
- Sibling handoff stuck after 3 of your iterations
- On `ask_human.py` timeout: post fallback decision in the thread so you
  see it later on your phone

Soft `notify.py` (no reply needed) for: milestones, unexpected findings,
long tasks, pre-risky-change warnings, sibling handoff acknowledgments.

## Typical workflow

1. **One-time**: create a dedicated Discord channel, give the bot
   (`Message Content Intent`, `Manage Messages`, `Manage Threads`, plus the
   usual messaging perms) access only to it, grab channel + user IDs.
2. **Per project**: `c3r init <repo>` walks the wizard — agents, roles,
   models, focus statements, GPU lock, base branch, env activation,
   max_agents cap, fix_plan seeding via `$EDITOR`. Auto-detects live usage
   from Firefox cookies.
3. **Launch**: `c3r launch <repo>` spins up tmux with agent windows, the
   logs window, and the listener.
4. **Watch**: `c3r watch <repo>` is your primary dashboard.
5. **Talk**: reply in a Discord thread or `c3r ping <agent> <msg>`.
6. **Pause/intervene**: `c3r pause` before edits, then `c3r resume`.
7. **Scale up**: agents spawn their own sub-agents when warranted.
   `c3r kill <name>` any of them anytime.
8. **Upgrade in place**: `c3r upgrade <repo>` pulls latest c3r and
   re-renders templates without losing any agent state.
9. **Ship**: review `agent/<name>` branches → merge into `c3r/<project>`
   → merge into main on your schedule.

## Not in scope

- **No npm / pip deps.** Pure stdlib Python + bash. `claude` CLI is the
  only external requirement.
- **No web UI.** Discord threads + `c3r watch` cover the dashboard role.
- **No cross-project orchestration.** Each `c3r init` is scoped to one repo.
- **No automatic merge back to main.** Intentional — you review what
  agents produced before it touches main.
- **No cloud or telemetry.** Runs entirely on your local machine.
