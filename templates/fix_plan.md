# fix_plan.md — experiment queue (seed)

The top of this file is the next few experiments the agent should run, in order.
The agent appends new proposals here; the human prunes/reorders as needed.

Replace these placeholders with your actual starting tasks before launching.

## Queue

1. **exp_001** — baseline reproduction. Run the current config unchanged; confirm
   metrics match the last logged result in `RESEARCH_LOG.md`. Hypothesis: the
   environment is deterministic enough that reruns converge within ±5% on the
   primary metric.

2. **exp_002** — single-variable perturbation. Pick the most recently-touched
   hyperparam and bump it one step in the direction suggested by the prior log entry.

3. **exp_003** — ablation of the most recently-added reward term (if this is a
   policy agent) or observation term (if perception). Verify it's pulling its weight.

## Notes

- Every entry here should name ONE change only.
- If you want to queue a multi-variable sweep, split it into N sequential entries.
- When an experiment completes, move it from here into `RESEARCH_LOG.md` with results.
