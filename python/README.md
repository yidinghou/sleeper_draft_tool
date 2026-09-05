# vorp

Pure valuation logic for the draft tool: per-position replacement level and
value-over-last-rostered, derived from projections. See
`../docs/spec/vorp/` for the specs this implements.

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
