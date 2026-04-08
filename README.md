# c3r — Continuous Context Claude Research

A project-agnostic harness for running **multiple Claude Code research agents
in parallel** on a local project, with **Discord threads** as the
human-in-the-loop interface, **git worktrees** for per-agent isolation, and
**agent hierarchy** (agents can spawn and kill sub-agents intelligently).

## What c3r gives you

- **Multi-agent continuous loop** — N top-level agents (usually 2–4) on a
  minimal ~50-line `claude -p` wrapper. No npm, no pip, no Ralph.
- **Agent hierarchy** — any running agent can spawn a bounded sub-agent
  via `$C3R_BIN/c3r spawn <name> <role> "<focus>"`, and kill it when done.
  Parent links are auto-filled. Killing a parent cascades to descendants.
- **Discord thread per agent** (top-level and sub-agents alike, with
  descriptive titles like `↳ lit-portela · read and summarize the Portela
  2025 paper`). Reply inside a thread to send the agent an INBOX message;
  agent responses and alerts land in the same thread.
- **Persistent status board** — one pinned Discord message edited in place,
  rendering the full agent tree with status, iter count, context %, and
  time-since-last-iteration. Updates on every heartbeat.
- **Cross-branch awareness** — `.c3r/SIBLINGS.md` is auto-regenerated at the
  start of every iteration with a fresh snapshot of every other agent's
  recent commits, modified files, and ready-to-paste `git show` commands.
  Agents stay coordinated without manual merging.
- **Sandbox enforcement** — a Claude Code `PreToolUse` hook rejects Write /
  Edit / NotebookEdit file paths outside the agent's own worktree. Agents
  cannot accidentally (or intentionally) write to `~/Downloads`, other
  agents' worktrees, or your main repo. `/tmp` is allowed for scratch.
- **Cooperative pause/resume** that never kills in-flight iterations.
- **Per-iteration context % alerts** at 25 / 50 / 75 / 100% of the 200k
  window — 75% and 100% @mention you in the agent's thread.
- **GPU lock** (flock) so concurrent agents can't OOM a shared GPU.
- **Circuit breaker** trips after 5 consecutive failures (auto-pause + ping).
- **Project environment activation** via `.c3r/env.sh` sourced each
  iteration — any venv, conda, CUDA, or cargo setup plugs in cleanly.
- **Live dashboard** (`c3r watch`) showing agent tree, last-3 INBOX messages
  with responses, recent log entries, and agent status at 1s refresh.
- **Fully stdlib Python + bash** — no open ports, no extra deps.

## Quick start

```bash
git clone https://github.com/DJRGVC/c3r ~/Research/c3r
~/Research/c3r/c3r install       # symlinks into ~/.local/bin
c3r init ~/Research/YourProject  # interactive wizard
c3r launch ~/Research/YourProject
c3r watch ~/Research/YourProject
```

See [SETUP.md](SETUP.md) for the full walkthrough including Discord bot
creation (MESSAGE CONTENT INTENT + Manage Threads required).

## CLI

```
SETUP
  c3r install                Symlink c3r into ~/.local/bin
  c3r init [path]            Interactive project wizard (agents, roles,
                             models, GPU lock, base branch, env activation,
                             Discord credentials, max_agents cap)
  c3r doctor [path]          Verify env, tools, Discord reachability
  c3r config                 Show saved config file

RUNNING
  c3r launch [path]          Start tmux session (one window per agent + listen + logs)
  c3r attach [path]          Attach to the running tmux session (alias: a)
  c3r stop [path]            Kill the tmux session (non-destructive)
  c3r pause [path]           Cooperatively pause all agents
  c3r resume [path]          Resume paused agents
  c3r watch [path] [sec]     Live dashboard with agent tree + INBOX + logs (alias: w)
  c3r status [path]          Print text status + force Discord board refresh
  c3r logs [path] [agent]    Tail RESEARCH_LOG.md for one or all agents

AGENT MANAGEMENT
  c3r spawn [path] NAME ROLE "FOCUS" [--model M] [--parent N]
                             Dynamically create a new agent. Auto-fills
                             parent from $C3R_AGENT_NAME when called by an
                             agent. Respects max_agents cap. Adds tmux
                             window live if session is running.
  c3r kill [path] NAME       Non-destructive stop (cascades to descendants).
                             Top-level: keeps thread + posts farewell.
                             Sub-agent: deletes thread entirely.
  c3r reset [path] NAME      Destructive: delete worktree + branch.

HUMAN ↔ AGENT
  c3r ping [path] NAME MSG   Send a message to an agent's INBOX
  c3r ask "question" [--choices a b c] [--multi]
                             Send yourself a Discord question (test harness)
  c3r board [path] bump|update
                             Manage the persistent Discord status board
  c3r listen [path]          Foreground Discord → INBOX listener

MAINTENANCE
  c3r update                 git pull c3r itself
  c3r uninstall              Remove ~/.local/bin symlink
  c3r help [command]         Overview or per-command detailed help
```

In Discord, from the project channel:

```
!c3r help | status | pause | resume | ping <agent> <message>
```

And inside any agent's thread, just type a message — the listener auto-ingests
it into that agent's `INBOX.md` and reacts with ✓ to acknowledge.

## Architecture at a glance

```
your project repo (e.g. ~/Research/YourProject)
├── .c3r/
│   └── state.json             single source of truth: agents, threads, cap, paused
├── scripts/c3r → c3r/bin      symlinked helper tools (ask_human, gpu_lock, etc.)
│
├── main, feature branches...  untouched by c3r
│
└── c3r/<project> branch       dedicated base branch for agent forks

(sibling worktrees live next to the repo)
~/Research/YourProject-policy/   on branch agent/policy (forked off c3r/project)
│   .c3r/
│     PROMPT.md                 non-negotiable rules + role template
│     fix_plan.md               experiment queue (human seeds, agents consume)
│     RESEARCH_LOG.md           append-only log, every iter writes an entry
│     SIBLINGS.md               auto-regen each iter: other agents' work
│     INBOX.md                  messages waiting to be processed
│     INBOX_ARCHIVE.md          processed messages with agent responses
│     agent.conf                model, cooldown, fail cap, thread id
│     env.sh                    project venv/CUDA activation (sourced each iter)
│     PAUSED                    flag file; presence = pause between iters
│   .claude/
│     settings.json             sandbox hook (rejects writes outside worktree)
│
~/Research/YourProject-perception/  same structure, branch agent/perception
```

## Project environment activation

c3r knows nothing about your project's tooling. You tell it once at init time:

```
Activation command (or empty): source /path/to/venv/bin/activate && export WANDB_API_KEY=...
```

This goes into `.c3r/env.sh` in every worktree and is sourced at the start
of every iteration. Sub-agents spawned via `c3r spawn` inherit the same
`env.sh`. When your project env changes, edit `env.sh` once per worktree
and the next iteration picks it up.

### Weights & Biases

If the project uses wandb, agents can read run metrics via the wandb Python
API (non-blocking, works for in-progress runs too) and log from their own
training scripts. Set `WANDB_API_KEY` in `.c3r/env.sh` or run `wandb login`
once outside c3r to populate `~/.netrc`. The PROMPT template explicitly
teaches agents the Python API pattern for reading runs.

## Safety properties

1. **Sandbox** — Claude Code PreToolUse hook rejects Write / Edit /
   NotebookEdit to file paths outside `$C3R_WORKTREE` (or `/tmp`). Agents
   physically cannot write to `~/Downloads`, other worktrees, or elsewhere.
2. **Base branch isolation** — agents never touch `main`. They fork from
   `c3r/<project>` → `agent/<name>` and commit only there. You merge back
   manually on your review schedule.
3. **GPU lock** — `gpu_lock.sh` uses `flock` so two agents can't OOM the GPU.
4. **Iteration timeout** — each `claude -p` call is wrapped in `timeout
   $ITERATION_TIMEOUT_SEC` (default 5400s = 90 min). Agents are told about
   the cap in PROMPT.md and are required to save training checkpoints at
   least every 10 minutes so a timeout doesn't waste the run — the next
   iteration resumes from the latest checkpoint. Set to empty string in
   `agent.conf` to disable entirely.
5. **Circuit breaker** — 5 consecutive failures auto-pause the agent and
   @mention you in Discord.
6. **max_agents cap** — global, asked at init. `c3r spawn` refuses with a
   clear error when full so a runaway agent can't spawn infinitely.
7. **Permission model for kill** — an agent may only kill itself or
   descendants in its own subtree, not siblings or ancestors.
8. **Cooperative pause** — `c3r pause` touches flag files; in-flight
   iterations (including long GPU runs) finish cleanly before agents stop.
9. **Model default** — Sonnet 4.6 everywhere; you can flip individual
   agents to Opus in their `agent.conf` and restart. Avoids burning a
   Max-plan weekly Opus quota by accident.

## Proactive communication

Agents are explicitly instructed to reach out to you on their own initiative,
not only in response to your messages. Mandatory ping triggers:

- Environment / binary failure (don't retry blindly, ask)
- Permission denied on a path the agent needs
- `fix_plan.md` exhausted (needs direction)
- Three consecutive failed iterations (before the circuit breaker hits 5)
- Architectural decisions affecting main-branch code
- Sibling handoff stuck after 3 iters

And softer `notify.py` (no reply needed) for: milestones, unexpected
findings, long tasks, pre-risky-change warnings, sibling handoff pings.

## Typical workflow

1. **One-time**: create a dedicated Discord channel for the project, give
   the bot (`Message Content Intent`, `Manage Threads`, and the usual
   messaging perms) access to it, grab channel + user IDs.
2. **Per project**: `c3r init <repo>` walks the wizard — agents, roles,
   models, focus statements, GPU lock, base branch, env activation,
   max_agents cap, fix_plan seeding.
3. **Launch**: `c3r launch <repo>` spins up the tmux session with one
   window per agent + a listener + a logs tail.
4. **Watch**: `c3r watch <repo>` is your primary dashboard. Leave it
   running in a spare terminal.
5. **Talk**: reply in a Discord thread to message an agent, or
   `c3r ping <agent> <msg>` from the CLI.
6. **Intervene**: `c3r pause` before tweaking anything, `c3r resume`
   after. Edit `.c3r/fix_plan.md` or `.c3r/PROMPT.md` directly; agents
   re-read them at the top of each iteration.
7. **Scale up**: agents spawn their own sub-agents when a bounded task
   warrants it. You can `c3r kill <name>` any of them anytime.
8. **Ship**: review `agent/<name>` branches → merge into `c3r/<project>`
   → merge into main on your schedule.

## Not included / out of scope

- **No npm / pip deps.** Pure stdlib Python + bash. `claude` CLI is the
  only external dependency, and it's the whole point.
- **No web UI.** Discord threads + `c3r watch` cover the "dashboard" use
  case; a browser dashboard adds surface area without adding signal.
- **No cross-project orchestration.** Each `c3r init` is scoped to one
  project repo. Run multiple independent projects in separate terminals
  if you need to.
- **No automatic merge back to main.** Intentional — you review what
  agents produced before it touches main.
- **No cloud API keys or hosting.** Runs entirely on your local machine.
