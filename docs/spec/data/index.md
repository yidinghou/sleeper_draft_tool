# The data pipeline

## What this produces

Every dollar and every VORP figure in this tool rests on two CSVs, and this
module is how they get made. Both are TypeScript scripts that fetch live feeds,
join a hand-scraped snapshot, and write a flat CSV into `data/`:

1. **`data/projections-{season}.csv`** — the load-bearing one. It fuses the
   Sleeper player dump, the Sleeper season/weekly projections, and the
   hand-scraped Sleeper draft board into one row per draftable player, with a
   single `season_pts_half_ppr` and a `pts_source` flag saying whether that
   number came from the board (preferred) or the API. This is the file the VORP
   engine reads.
2. **`data/boberto-{season}.csv`** — the second opinion. It pulls an independent
   FantasyPros projection and real market AAV from `boberto.app`, recomputes
   half-PPR points from the raw stat line, and matches each row back to a Sleeper
   `player_id` so it lines up against the projections table.

## Why two scripts, not one

They answer to different sources and different failure modes. The projections
export is authoritative — its output is what gets priced, and its hardest part
is keeping the scraped board's `$`/`rank`/`pts` a consistent snapshot. The
Boberto export is corroborating — its output is a sanity check and a market
reference, and its hardest part is *matching* a messy external feed onto Sleeper
ids without inventing wrong matches. Keeping them apart means the pricing input
never depends on the second feed's match quality.

## The specs

| | What it covers |
| --- | --- |
| [01 · Projections export](01-projections-export.md) | `export-projections.ts` + `csv_loader.py`: Sleeper players, season + weeks-1-3 projections, joined to the scraped board, with the board-preferred `pts_source` rule |
| [02 · The Boberto twin](02-boberto-twin.md) | `export-boberto.ts` + `src/boberto.ts`: the FantasyPros feed, market AAV, half-PPR from the stat line, and the player-matching correctness argument |

The engine that consumes `projections-{season}.csv` is documented in
[`../vorp/index.md`](../vorp/index.md); the reproduction steps for rebuilding
both CSVs from scratch are in [`guide.md`](guide.md). The Sleeper endpoint
contract these scripts call — including why the auction dollar value can only be
hand-scraped — lives in [`../../sleeper-api.md`](../../sleeper-api.md).
