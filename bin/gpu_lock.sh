#!/usr/bin/env bash
# gpu_lock.sh — serialize GPU access between concurrent research agents.
# Usage: gpu_lock.sh <command> [args...]
# Example: gpu_lock.sh python scripts/rsl_rl/train.py --task Isaac-... --headless
#
# The flock is held for the entire lifetime of the wrapped command, so a
# second agent that tries to train at the same time will block here until
# the first agent's run finishes. Prevents OOM from two Isaac Lab processes
# on the same GPU.
set -euo pipefail

LOCK_FILE="${C3R_GPU_LOCK:-/tmp/c3r_gpu.lock}"
exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    echo "[gpu_lock] GPU busy; waiting for other agent to finish..." >&2
    flock 9
    echo "[gpu_lock] GPU acquired." >&2
fi

echo "[gpu_lock] $(date -Iseconds) running: $*" >&2
"$@"
