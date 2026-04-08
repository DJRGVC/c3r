#!/usr/bin/env bash
# c3r — one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/DJRGVC/c3r/main/install.sh | bash
#
# What this does:
#   1. Verifies dependencies (git, python3, tmux, flock, setsid, claude)
#   2. Clones c3r to ~/.local/share/c3r (or pulls if already there)
#   3. Symlinks the c3r CLI into ~/.local/bin
#   4. Prints next steps
#
# What this does NOT do:
#   - Touch any project directory (run `c3r setup <repo>` for that)
#   - Configure Discord (the wizard handles it on first `c3r setup`)
#   - Run as root or write outside $HOME
set -euo pipefail

REPO_URL="${C3R_REPO_URL:-https://github.com/DJRGVC/c3r}"
INSTALL_DIR="${C3R_INSTALL_DIR:-$HOME/.local/share/c3r}"
BIN_DIR="${C3R_BIN_DIR:-$HOME/.local/bin}"
BRANCH="${C3R_BRANCH:-main}"

# --- pretty output ---
if [ -t 1 ]; then
    BOLD=$'\e[1m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; DIM=$'\e[2m'; RESET=$'\e[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; DIM=""; RESET=""
fi
info() { echo "${BOLD}[c3r-install]${RESET} $*"; }
ok()   { echo "${GREEN}[c3r-install] ✓${RESET} $*"; }
warn() { echo "${YELLOW}[c3r-install] ⚠${RESET} $*" >&2; }
die()  { echo "${RED}[c3r-install] ✗${RESET} $*" >&2; exit 1; }

# --- dependency check ---
info "checking dependencies..."
missing=()
for cmd in git python3 tmux flock setsid; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd → $(command -v "$cmd")"
    else
        missing+=("$cmd")
        warn "$cmd not found"
    fi
done
if command -v claude >/dev/null 2>&1; then
    ok "claude → $(command -v claude)"
else
    warn "claude CLI not found — install Claude Code from https://docs.claude.com/en/docs/claude-code"
    warn "  c3r will install but agents can't run until claude is available"
fi

if [ "${#missing[@]}" -gt 0 ]; then
    die "missing required dependencies: ${missing[*]}.  Install with: sudo apt install git python3 tmux util-linux  (or your distro's equivalent)"
fi

# --- clone or update ---
if [ -d "$INSTALL_DIR/.git" ]; then
    info "updating existing c3r at $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --quiet origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH" --quiet
    ok "pulled latest from $REPO_URL ($BRANCH)"
else
    info "cloning c3r to $INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" 2>&1 | grep -v '^Cloning' || true
    ok "cloned to $INSTALL_DIR"
fi

VERSION="$(cat "$INSTALL_DIR/VERSION" 2>/dev/null | tr -d '[:space:]' || echo unknown)"
GIT_HEAD="$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo ?)"
ok "c3r version $VERSION ($GIT_HEAD)"

# --- symlink ---
mkdir -p "$BIN_DIR"
LINK="$BIN_DIR/c3r"
if [ -L "$LINK" ] || [ -f "$LINK" ]; then
    rm -f "$LINK"
fi
ln -s "$INSTALL_DIR/c3r" "$LINK"
ok "symlinked $LINK → $INSTALL_DIR/c3r"

# --- PATH check ---
if ! command -v c3r >/dev/null 2>&1; then
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;  # on PATH but shell hasn't rehashed yet
        *)
            warn "$BIN_DIR is not on your PATH"
            echo
            echo "  Add this to your shell rc (~/.bashrc or ~/.zshrc):"
            echo "    ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
            echo
            echo "  Then reload with: source ~/.bashrc  (or open a new terminal)"
            ;;
    esac
fi

cat <<EOF

${GREEN}${BOLD}c3r installed.${RESET}

${BOLD}Next:${RESET}
  ${DIM}# Verify install${RESET}
  c3r doctor

  ${DIM}# First-time project setup (interactive Discord bot wizard)${RESET}
  c3r setup ~/path/to/your/project

  ${DIM}# Or jump straight in if you already know what you want${RESET}
  c3r init  ~/path/to/your/project

  ${DIM}# Once set up, launch the agents${RESET}
  c3r launch ~/path/to/your/project
  c3r watch  ~/path/to/your/project

${BOLD}Docs:${RESET}
  $INSTALL_DIR/SETUP.md
  $INSTALL_DIR/README.md

EOF
