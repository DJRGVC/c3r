# videos/

Video clips embedded in Quarto pages. Drop MP4 (H.264, web-compatible)
files here.

## Folder layout

```
videos/
├── shared/                # project demos, conference clips, headline videos
├── <agent-name>/          # one folder per agent — your agent's videos go here
│   └── <descriptive_name>_iter_<NNN>.mp4
└── README.md              # this file
```

## How agents reference their videos

From inside `agents/<agent-name>.qmd`, use HTML5 `<video>` (Quarto
markdown supports raw HTML):

```html
<video controls width="100%" src="../videos/<agent-name>/iter_017_replay.mp4"></video>
```

Or with a poster image (recommended for performance — first frame
shown until user clicks play):

```html
<video controls width="100%"
       poster="../images/<agent-name>/iter_017_thumb.png"
       src="../videos/<agent-name>/iter_017_replay.mp4">
</video>
```

## File size + format

- **Use H.264 MP4** for browser compatibility. AV1/HEVC won't play in
  every browser; AVI/MOV/MKV definitely won't.
- **Keep files under ~10MB** if possible — GitHub Pages serves them
  fine, but bigger files inflate the gh-pages branch and slow down
  cloning. If you need a longer clip, link to YouTube/Vimeo instead
  (Quarto supports embedded video via shortcodes).
- **Compress before committing**: `ffmpeg -i raw.mp4 -c:v libx264
  -crf 28 -preset slow -an out.mp4` typically halves file size with
  no perceptible quality loss for technical demos.

## What NOT to put here

- Raw simulator captures > 50MB — compress first
- Training run videos lasting hours — clip the relevant 30 seconds
- Anything you don't want public on GitHub Pages

The auto-publish workflow includes `videos/` in the deployed site.
