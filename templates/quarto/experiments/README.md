# experiments/

Deep-dive write-ups of significant experiments. When a result is too
substantial for a one-paragraph entry on an agent's main page, create
a dedicated `.qmd` file here.

## Folder layout

```
experiments/
├── 2026-04-08_sigma_curriculum_sweep.qmd
├── 2026-04-09_d435i_camera_smoke_test.qmd
├── 2026-04-10_perception_ekf_tuning.qmd
└── README.md              # this file
```

## When to create an experiment write-up

- A result that justifies a full methodology + figures + table + discussion
- Anything you'd want to send a collaborator as a standalone read
- A negative result worth documenting so someone doesn't repeat it
- A multi-iteration sweep with a hero figure
- Anything you'd put in a paper appendix

## When NOT to create one

- A one-paragraph result fits perfectly fine on `agents/<your-name>.qmd`
- A failed iteration with no insights
- Routine reward-weight tweaks

If in doubt, write a short entry on your agent page first. If the
entry grows past ~300 words, that's the signal to break it out into
its own experiment file.

## Filename convention

`YYYY-MM-DD_short_descriptive_name.qmd` — date prefix sorts naturally,
underscore-separated lowercase, descriptive enough that you can tell
what it is from the filename alone.

## Required front matter

```yaml
---
title: "Sigma curriculum sweep"
description: "Tested σ ∈ {0.05, 0.08, 0.13, 0.20} for ball juggle"
date: 2026-04-08
author: "perception"        # which agent ran it
categories: [curriculum, ball_juggle, perception]
---
```

The `categories` populate the experiment listing's filter tags.

## Suggested structure

```
## Motivation
## Setup
## Results
  (tables, figures from images/<your-agent>/)
## Interpretation
## What's next
## Links
  - [commit abc1234](../<repo>/commit/abc1234)
  - [training log](../path/to/log.md)
```

Link to it from your agent page entry so readers can drill in:

```markdown
**Result**: see [Sigma curriculum sweep write-up](../experiments/2026-04-08_sigma_curriculum_sweep.qmd) for the full table.
```
