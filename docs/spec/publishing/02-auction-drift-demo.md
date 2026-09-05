# 02 · Auction-drift demo (FAQ)

> **Correction to current code.** This spec describes `scripts/draft_demo.py`
> repricing via `price_board` from `python/vorp/board.py` — that module doesn't
> exist in this repo. `draft_demo.py`'s actual `snapshot()`/`seat_rows()`
> reprice with their own logic directly against `vorp.league.teams.LeagueState`
> and `vorp.models.blend_weights`, not a shared `vorp.board` module. Every
> `price_board`/`python/vorp/board.py` reference below (including the
> Reference section's "Depends on") describes the not-yet-implemented `07`
> design, not what `draft_demo.py` actually calls today. Also, `build_draft_demo.py`
> writes its page into gitignored `artifacts/`, not a tracked `pages/`.

### What does this build?

One self-contained page that shows what a sale does to every price still on the
board, across four scripted mispricing runs. `scripts/draft_demo.py` replays a
fixed sale order through four different mispricing rules — `fair-market`,
`bargain-run`, `panic-run`, `position-runs` — repricing the whole board after
every pick via `price_board`, and writes one JSON timeline per scenario.
`artifact/build_draft_demo.py` folds those four JSONs into a single tabbed page,
`pages/draft-demo-2026.html`. It is the demo surface for the live repricing in
[`../vorp/07-live-draft-board.md`](../vorp/07-live-draft-board.md).

### Why fold four scenarios into one page instead of linking five?

Because an earlier version emitted five cross-linked local files — a landing
page plus one per scenario — and that shape works from the filesystem and not at
all as an Artifact, where every page is its own URL and
`href="draft-demo-2026-panic-run.html"` resolves to nothing. On a phone it was
also just wrong: nobody wants to hold five links. One page with the four
scenarios behind a tab bar is browsable, publishable, and pocket-sized at once.

### Why a timeline per scenario rather than a price table?

Because the seat/slot model is deliberately *invisible* pre-draft — every slot
is open and the numbers equal the expansion it replaced. What it changes is what
happens *after* a sale: money leaving the room faster than value does makes
everyone left cheaper, and the reverse makes them dearer. A static table can't
show motion, so each scenario ships a frame per pick and the page scrubs through
them.

### How does `draft_demo.py` actually work?

It solves the opening board once, then replays it under each scenario. The sale
`order` is fixed across all four — richest by market price (`sleeper_dollar`)
first — so "pick index" means the same player in every scenario; only what he
sells for changes. Each scenario is a `multiplier(position, i, sold) -> factor`
applied to market price, and the sale lands at `max(min_bid, round(market ×
factor))`:

```
fair-market    factor = 1.0                          (control)
bargain-run    0.55 if i < 15 else 1.0               (first 15 go 45% off)
panic-run      1.40 if i < 15 else 1.0               (first 15 go 40% over)
position-runs  1.35 if RB & sold[RB] < 12;
               0.75 if WR & sold[WR] < 14; else 1.0  (two positions, opposite)
```

Each sale is `state.sell(pid, position, amount, seat_id=i % teams)`, then
`snapshot` — a thin wrapper over `price_board`, the same implementation the live
server runs on — reprices whatever is left. The result is a `frames` list: frame
0 is the opening board, then one frame per pick carrying the pool, spots left,
the VORP exchange rate, per-position levels, every remaining player's row, and
the seats. Each scenario is written to `data/draft-demo-{season}-{key}.json`,
plus an index `data/draft-demo-{season}.json` naming them.

### How does `build_draft_demo.py` fold four JSONs into one page?

Without re-solving and without forking the template. It reads the JSON
`draft_demo.py` already wrote (keeping a ~four-minute solve out of a build that
should take a second), and it lifts the stylesheet, markup, and render script
out of `scripts/templates/draft_demo.html` *at build time* rather than copying
them. Extraction slices the source at exactly-once anchors: the end of
`</style>`, the start of `<div class="wrap">`, the `<script id="demo-data">`
tag, and the render IIFE's `(function () {` / `})();` boundaries. It then strips
three lines the merged page has no use for — the "all scenarios" back-link
markup, the line that sets its `href`, and the bootstrap that reads the single
payload out of the DOM — each also asserted to appear exactly once. Any count
other than one raises `SystemExit`, so a template edit that moves an anchor
fails the build loudly instead of shipping a page that loads and does nothing.
The three pieces are re-hosted in `artifact/templates/scenario_shell.html`,
whose tab bar re-clones the markup and re-runs the render script per scenario.

### Why hoist the shared board out of the four payloads?

Because the four scenarios start from one solved opening board, so everything
that is a property of the board rather than the run — `season`, `window`,
`w_floor`, the `league` block, and the 192-row `players` list with its opening
prices — is identical across all four by construction. `merge_payloads` asserts
they agree field-by-field and stores that block once; each scenario keeps only
its `key`, `title`, `blurb`, `frames`, and `ledger`. That hoist is most of what
keeps the merged page near the size of a single scenario instead of four times
it.

### What's the output, precisely?

`artifacts/draft-demo-2026.artifact.html` (fragment, gitignored) and
`pages/draft-demo-2026.html` (standalone) — one page, four tabs, each scrubbing
its own per-pick timeline over the shared opening board. A plain `python
scripts/draft_demo.py 2026` produces the per-scenario JSON, the index, and the
merged page in one run; running `build_draft_demo.py` directly rebuilds the page
from existing JSON without re-solving.

### What does that look like in practice?

- **`panic-run`:** the first 15 picks pay 40% over, so money leaves faster than
  value — every unsold player reprices down, tab by tab.
- **`position-runs`:** RB and WR move opposite ways at once, and each position's
  bar only starts to slide once it sells past its own concrete slots.
- **Worked example:** in `bargain-run` a top pick the market prices at $60,
  taken in the first 15 (`i < 15`), sells for `max(1, round(60 × 0.55))` = **$33**.
  Twenty-seven dollars that "should" have left the room stay in it, so
  `price_board` lifts the per-spot pool and every player still on the board gets
  dearer — the opposite of what a static sheet quoting opening prices would say.

### What happens if a scenario's opening board doesn't match the others?

`merge_payloads` refuses to build. If any of the four disagrees on `season`,
`window`, `w_floor`, `league`, or `players`, they no longer share one opening
board and therefore cannot share one page, so the merge raises `SystemExit`
naming the field. The wrong outcome — quietly merging mismatched boards behind
one tab bar — is exactly what the assertion exists to prevent; re-run
`draft_demo.py` for all four so they solve from the same board.

### What's the catch?

The demo is only as honest as its scripted multipliers. `bargain-run` and
`panic-run` are hand-picked mispricings (0.55 and 1.40 on the first 15 picks),
not observed drafts, so the page shows how the board *would* react to a run, not
that any real room drafts that way. And like the model it demonstrates, each
reprice assumes the rest of the room spends rationally — the same assumption the
scripted run just violated.

### How does it stay under the Artifact size limit?

`build_draft_demo.py` measures the merged fragment and raises `SystemExit` if it
exceeds 16 MB. The board hoist is what keeps it comfortably under: four full
payloads would carry four copies of the 192-row player list, and folding them to
one is most of the saving.

---

## Reference

**Depends on:** `python/vorp/board.py` (`price_board`,
[`../vorp/07-live-draft-board.md`](../vorp/07-live-draft-board.md)) for the
repricing; `python/vorp/league/teams.py` (`LeagueState`) for the residual state;
`data/projections-2026.csv` and its market `sleeper_dollar` column for the sale
order and amounts; `python/artifact/html_page.py` (`write_pair`) for the two-file
write. **Implemented in:** `python/scripts/draft_demo.py` (the four `SCENARIOS`,
`run_scenario`, `write_scenario_json`) and
`python/artifact/build_draft_demo.py` (`extract`, `merge_payloads`, `build`),
over the templates `python/scripts/templates/draft_demo.html` and
`python/artifact/templates/scenario_shell.html`. **Done when:** `python
scripts/draft_demo.py 2026` writes four `data/draft-demo-2026-{key}.json` plus
the index, folds them into `pages/draft-demo-2026.html` and the gitignored
fragment, the four scenarios agree on the hoisted board, every extraction anchor
is found exactly once, and the merged fragment is under 16 MB.

| Input | Description |
| --- | --- |
| `data/projections-2026.csv` | projected points and the `sleeper_dollar` market price |
| `SCENARIOS` | the four `multiplier(position, i, sold)` mispricing rules |
| `--picks` | how many of the fixed richest-first order to sell (default 60) |
| `--w-floor` | the blend dial passed to `price_board` (default 1.0, pure VORP) |
| `draft_demo.html` / `scenario_shell.html` | the fragment template and the merge shell |

| Output | Description |
| --- | --- |
| `data/draft-demo-2026-{key}.json` | one per scenario: `frames`, `ledger`, and its copy of the shared board |
| `data/draft-demo-2026.json` | index naming the scenarios, read by `build_draft_demo.py` |
| `pages/draft-demo-2026.html` | the one tabbed standalone page |
| `artifacts/draft-demo-2026.artifact.html` | the publishing fragment (gitignored) |
