#!/usr/bin/env bash
# init.sh — wire c3r into a target project repo.
#
# Usage: ./init.sh <target-repo-path> [agent-a-name] [agent-b-name]
#
# What it does:
#   1. Creates two git worktrees via setup_worktrees.sh
#   2. Inside each worktree, creates .ralph/ and drops in the PROMPT, fix_plan,
#      RESEARCH_LOG, and .ralphrc templates (naming PROMPT.md after the agent role).
#   3. Symlinks bin/ so tool updates to c3r propagate automatically.
#
# Does NOT: install Ralph itself, create Discord bot, launch tmux.
# See SETUP.md for those steps.
set -euo pipefail

C3R_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:?Usage: init.sh <target-repo-path> [agent-a] [agent-b]}"
A_NAME="${2:-policy}"
B_NAME="${3:-perception}"

TARGET="$(cd "$TARGET" && pwd)"
PARENT="$(dirname "$TARGET")"
REPO_NAME="$(basename "$TARGET")"

echo "[c3r] target: $TARGET"
echo "[c3r] agents: $A_NAME, $B_NAME"

# 1. Worktrees
"$C3R_DIR/scripts/setup_worktrees.sh" "$TARGET" "$A_NAME" "$B_NAME"

# 2. Per-worktree .ralph/ seed
seed_worktree() {
    local wt="$1" role="$2"
    local ralph="$wt/.ralph"
    mkdir -p "$ralph"
    if [ ! -f "$ralph/PROMPT.md" ]; then
        cp "$C3R_DIR/templates/PROMPT_${role}.md" "$ralph/PROMPT.md"
        echo "[c3r] seeded $ralph/PROMPT.md"
    else
        echo "[c3r] $ralph/PROMPT.md exists; leaving it alone"
    fi
    for f in fix_plan.md RESEARCH_LOG.md; do
        [ -f "$ralph/$f" ] || cp "$C3R_DIR/templates/$f" "$ralph/$f"
    done
    [ -f "$ralph/.ralphrc" ] || cp "$C3R_DIR/templates/ralphrc.example" "$ralph/.ralphrc"
}

seed_worktree "$PARENT/${REPO_NAME}-${A_NAME}" "$A_NAME"
seed_worktree "$PARENT/${REPO_NAME}-${B_NAME}" "$B_NAME"

# 3. Symlink bin/ into target as scripts/c3r (if not already present)
LINK="$TARGET/scripts/c3r"
mkdir -p "$TARGET/scripts"
if [ ! -e "$LINK" ]; then
    ln -s "$C3R_DIR/bin" "$LINK"
    echo "[c3r] symlinked $LINK -> $C3R_DIR/bin"
else
    echo "[c3r] $LINK already exists; leaving it alone"
fi

chmod +x "$C3R_DIR/bin/"*.sh "$C3R_DIR/bin/"*.py "$C3R_DIR/scripts/"*.sh 2>/dev/null || true

cat <<EOF

[c3r] init complete.

Next steps (see SETUP.md):
  1. Create Discord bot, invite to a server, export DISCORD_BOT_TOKEN/CHANNEL_ID/USER_ID
  2. Test ask_human.py standalone: \$C3R_DIR/bin/ask_human.py "test"
  3. Inside each worktree, run: ralph-enable-ci
  4. Edit .ralph/fix_plan.md in each worktree with 3-5 concrete starting tasks
  5. Launch: $C3R_DIR/scripts/launch_agents.sh $TARGET $A_NAME $B_NAME
EOF
