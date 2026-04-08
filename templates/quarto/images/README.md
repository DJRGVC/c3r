# images/

Static figures referenced by Quarto pages. Drop PNG/JPG/SVG files here
and reference them from `.qmd` pages with markdown image syntax.

## Folder layout

```
images/
├── shared/                # cross-agent figures, project diagrams, headline plots
├── <agent-name>/          # one folder per agent — your agent's figures go here
│   └── <descriptive_name>_iter_<NNN>.png
└── README.md              # this file
```

## How agents reference their figures

From inside `agents/<agent-name>.qmd`:

```markdown
![Sigma curriculum sweep — best stage at σ=0.08](../images/<agent-name>/sigma_sweep_iter_017.png){width=80%}
```

The `../` is because the agent page lives in `agents/` and the image
lives in `images/`. The `{width=80%}` is optional but recommended for
mobile readability.

## Filename conventions

- **One file = one figure**. Don't bundle.
- **Lowercase + underscores**. `sigma_sweep_iter_017.png` not `SigmaSweep17.png`.
- **Include the iteration number** when relevant: makes git history readable.
- **Prefix with the topic** so similar figures sort together:
  `reward_curve_baseline_iter_005.png`,
  `reward_curve_with_dr_iter_022.png`.

## What NOT to put here

- Source data (CSVs, npz, npy) — those go in `experiments/<name>/` next to the write-up
- Videos — those go in `videos/<agent-name>/`
- Generated PDFs — those go in `experiments/<name>/`
- Cache files, intermediate exports, scratch — keep out of `images/`

The auto-publish workflow includes the `images/` directory in the
deployed site, so anything here ships to GitHub Pages publicly.
