# thesis
PhD Dissertation of Sejin Kim

**Reproducible Deep Learning for Head and Neck Radiotherapy**, Department of Medical Biophysics, University of Toronto (2026).

## Website

`docs/` holds the thesis as a single scrolling web page (`docs/index.html` plus WebP figures in `docs/figures/`).
It can be served as-is with GitHub Pages (Settings → Pages → deploy from branch, folder `/docs`).

To preview locally:

```bash
python3 -m http.server -d docs 8000
```

## Deploying to Cloudflare Workers

`wrangler.jsonc` serves `docs/` as static assets on a Worker named `thesis` (no Worker script).
With `CLOUDFLARE_API_TOKEN` (needs **Workers Scripts: Edit**) and `CLOUDFLARE_ACCOUNT_ID` set:

```bash
npm install
npm run deploy
```

## Rebuilding from the manuscript

The page is generated from the dissertation `.docx`. Requires `pandoc` and Python with `beautifulsoup4` and `Pillow`.

```bash
python3 tools/build_site.py path/to/thesis.docx
```

- `tools/build_site.py` converts the manuscript, groups figures and tables with their captions, links in-text
  citations to the reference list and figure/table/section mentions to their targets, and assembles the page.
- `tools/src/` holds the page template, stylesheet, script, and the interactive figures (cohort dot grid,
  negative-control explorer, SCARF slope chart, iENE forest plot, threshold explorer, Dosarex pipeline).
- Chapter openers (kicker, hypothesis, headline numbers) are written in the `CHAPTERS` table at the top of
  `tools/build_site.py`; every figure there is quoted from the thesis text.
