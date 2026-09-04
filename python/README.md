# vorp

Pure valuation logic for the draft tool: per-position replacement level and
value-over-last-rostered, derived from projections. See
`../docs/spec/vorp/` for the specs this implements.

`scripts/` splits by league: `scripts/auction/` (the live bid-price board and
demos, league `1372724723108036608`) vs `scripts/snake/` (queue ranking and
Claude-in-Chrome autodraft, league `1386051970791378944`). `scripts/html_page.py`,
`replacement_level.py`, and `last_rostered.py` stay flat at `scripts/` root —
both leagues import them. `data/` mirrors the same split, with shared source
files (`projections-*.csv`, `boberto-*.csv`, `adp-*.csv`, and the
replacement-level/last-rostered json) at `data/` root.

**Split with the rest of the repo:** `src/sleeper.ts` and
`scripts/export-projections.ts` (TypeScript) own everything that talks to
the Sleeper API and produce `data/projections-{season}.csv`. Everything
under `python/` is pure logic — no network calls, no file I/O beyond the
report script reading that CSV. For now the two sides only talk through
that CSV; if live draft polling needs Python valuation on every poll tick,
that'll need a small bridge (a local HTTP call or a long-lived subprocess)
rather than a fresh CSV export per tick — not built yet.

## Setup

```bash
python3 -m pip install --user pytest
```

## Running tests

```bash
cd python
python3 -m pytest -v
```

## Running the scripts

Each reads the real projections CSV that `npm run export:projections`
produces, prints a table, and writes its result to a JSON config in
`data/` — `replacement-level-{season}.json` /
`last-rostered-{season}.json` — so other code can load the numbers without
recomputing them:

```bash
python3 python/scripts/replacement_level.py
python3 python/scripts/last_rostered.py
```
