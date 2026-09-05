# HTML publishing — reproduction guide

How to regenerate every page under this spec from a clean checkout. See
[`01-html-export-pipeline.md`](01-html-export-pipeline.md) and
[`02-auction-drift-demo.md`](02-auction-drift-demo.md) for what the machinery
does; this is the command sequence and what to expect out of it.

> **Two corrections to the commands/table below, matching current code (see
> the note atop [`01-html-export-pipeline.md`](01-html-export-pipeline.md)):**
> there is no tracked `pages/` directory — `write_pair`/`write_local` write
> everything into gitignored `artifacts/` today; and none of these build
> scripts actually import `../vorp/07-live-draft-board.md`'s model (it isn't
> implemented) — `draft_demo.py` reprices with its own `snapshot()`/`seat_rows()`
> logic directly against `vorp.league.teams.LeagueState`, not a `vorp.board`
> module.

## Prerequisites

- **Python 3.9+.** The `vorp` package declares no runtime dependencies
  (`python/pyproject.toml`), so nothing to install to build the pages. `pytest`
  is the only dev extra, needed only to run the test suite.
- **The projections CSV: `data/projections-2026.csv`.** Every build reads it
  through `vorp.csv_loader.projections_csv_path(season)`. It is produced by the
  TypeScript side (`npm run export:projections`, which owns everything that
  talks to the Sleeper API); the Python side only reads it. The seat-value and
  draft-demo builds also read its `sleeper_dollar` (market price) column.
- **The models in [`../vorp/`](../vorp/index.md)** — replacement level (`01`),
  last-rostered (`02`), and blended-bar pricing (`04`) underpin all builds;
  seat value (`08`) underpins the seat-value page. The build scripts import
  these directly; nothing here reimplements a model. (The live board, `07`,
  is not yet implemented and none of these scripts import it —
  `draft_demo.py` reprices with its own logic directly against
  `vorp.league.teams.LeagueState`.)

There are no console-script entrypoints in `pyproject.toml` — invoke the module
files directly. All commands below run from the **`python/` directory** (each
script puts `python/` on `sys.path` relative to its own location).

```bash
cd python
```

## Build commands

```bash
# 1. Seat-value page (../vorp/08). --verify re-solves every preset in Python.
python artifact/build_seat_value.py 2026 --verify

# 2. Blended-price page (../vorp/04). Standalone only, no Artifact fragment.
python scripts/blended_price.py 2026

# 3. Auction-drift demo (../vorp/07): solve four scenarios AND fold the page.
python scripts/draft_demo.py 2026

# 3b. Optional — rebuild the demo page from existing JSON, without re-solving.
python artifact/build_draft_demo.py 2026
```

Each takes an optional `season` positional (defaults to the league config's
season). Other flags: `build_seat_value.py` takes `--out` (fragment dir,
default `artifacts`), `--window`, and `--verify`; `blended_price.py` takes
`--window` and `--w-floor` (where the slider starts, default 0.5);
`draft_demo.py` takes `--picks` (default 60), `--w-floor` (default 1.0, pure
VORP), and `--scenario` (default `all`, which also folds the page — a single
scenario writes JSON only).

## Expected outputs

| Command | Standalone page (`artifacts/`, gitignored) | Artifact fragment (`artifacts/`, gitignored) | Data (`data/`, gitignored) |
| --- | --- | --- | --- |
| `build_seat_value.py` | `seat-value-2026.html` | `seat-value-2026.artifact.html` | — |
| `blended_price.py` | `blended-price-2026.html` | *(none — uses `write_local`)* | `blended-price-2026.json` |
| `draft_demo.py` | `draft-demo-2026.html` | `draft-demo-2026.artifact.html` | `draft-demo-2026-{fair-market,bargain-run,panic-run,position-runs}.json` + `draft-demo-2026.json` |

Both the standalone page and the `.artifact.html` fragment land in gitignored
`artifacts/` today — there is no tracked `pages/` directory in this repo (see
the correction at the top of this guide and in
[`01-html-export-pipeline.md`](01-html-export-pipeline.md)). Each build prints
the paths it wrote and the fragment size.

## Gotchas

- **`--verify` is the seat-value parity guard.** The seat-value page re-solves
  the lineup in JavaScript, so the matching exists twice. `--verify` re-solves
  every `PRESET` through the real Python model and prints the numbers the page
  must reproduce, and it hard-fails (`SystemExit`) if a preset costs more than
  the budget can seat or if a preset name no longer resolves on the board (a
  projection refresh renumbered players). It does *not* automatically diff
  against the browser — the priced-number comparison is by eye. Run it whenever
  you touch the model or the template's JS.

- **The draft-demo extraction anchors must be exactly once.**
  `build_draft_demo.py` lifts the head, markup, and render script out of
  `scripts/templates/draft_demo.html` at build time. If a template edit moves or
  duplicates one of its boundary anchors (`</style>`, `<div class="wrap">`,
  `<script id="demo-data">`, the IIFE's `(function () {` / `})();`) or the three
  stripped navigation/bootstrap lines, the build raises `SystemExit` rather than
  shipping a page that loads and does nothing. Fix the template or update
  `build_draft_demo.py`'s anchors together.

- **The 16 MB Artifact limit.** `build_draft_demo.py` measures the merged
  fragment and refuses to finish if it exceeds 16 MB. The seat-value and
  blended-price fragments are tens of KB and never approach it.

- **Why draft-demo hoists the shared board.** The four scenarios start from one
  solved opening board, so the `league` block and the 192-row player list are
  identical across all four. `merge_payloads` asserts they agree and stores that
  block once; four un-hoisted copies would roughly quadruple the page and push
  it toward the 16 MB limit. If the four disagree on the board, the merge
  refuses — re-run `draft_demo.py` for all four so they solve from one board.

- **`draft_demo.py 2026` already builds the page.** It calls
  `build_draft_demo.build` at the end of its run, so you only need step 3b to
  rebuild the page from existing JSON without paying for the ~four-minute
  re-solve.
