# The data pipeline — reproduction guide

How to rebuild `data/projections-{season}.csv` and `data/boberto-{season}.csv`
from scratch. Concepts and the "why" live in [01](01-projections-export.md) and
[02](02-boberto-twin.md); this is the runbook.

## Prerequisites

- **Node + dependencies.** From the repo root:

  ```bash
  npm install
  ```

  The scripts run under `tsx` (see `package.json`); no build step, no global
  install.

- **The Sleeper board CSV**, `data/sleeper-board-{season}.csv`:

  ```
  player_id,sleeper_rank,bye_week,sleeper_proj_dollar,sleeper_board_pts_half_ppr
  ```

  This used to be hand-scraped from a logged-in browser, on the belief that the
  draft board's numbers were computed client-side and off the API. Reading the
  board's React state showed otherwise — the rows it renders come straight from
  the public projections feed, and the only number it really computes is `rank`,
  which is that feed ordered by `adp_half_ppr`. `npm run export:board` derives
  the whole file, and its output was checked against the live board.

  `sleeper_proj_dollar` is the exception and is still browser-only: it is an
  auction number the board derives client-side, and a snake draft has none at
  all. The exporter carries existing values forward from the previous CSV rather
  than blanking them, so re-running never destroys an auction snapshot.

  The projections export runs without this file, but then `sleeper_rank`,
  `bye_week` and `sleeper_proj_dollar` come out blank and every point falls back
  to the API. Commit the CSV — it is a point-in-time snapshot, worth re-running
  closer to draft day if values drift.

## Build order

1. **Export the board** → `data/sleeper-board-{season}.csv`. Do this first; the
   projections export joins against it.
2. **Export projections** → `data/projections-{season}.csv`. This is the file the
   Python VORP engine reads.
3. **Export the Boberto twin** → `data/boberto-{season}.csv`. Independent of step
   2; can run in either order relative to it.
4. **Run the tests** to confirm the matching machinery still resolves.

## Commands

```bash
# 1 — rank/bye/PTS for every projected player, derived from the public feed
npm run export:board 2026

# 2 — Sleeper players + season/weekly projections, joined to the board
npm run export:projections 2026

# 3 — FantasyPros projections + market AAV, matched to Sleeper ids
npm run export:boberto 2026

# 4 — unit tests (name normalization + player matching)
npm test
```

The season argument defaults to `2026` if omitted. Both export scripts create
`data/` if it's missing and overwrite the target CSV in place.

## Expected output

**`npm run export:projections 2026`** prints e.g. `Wrote <N> rows to
data/projections-2026.csv (<M> matched board data).` and writes a CSV whose
header is exactly:

```
player_id,player,position,team,sleeper_rank,bye_week,sleeper_proj_dollar,season_pts_half_ppr,pts_source,wk1_3_pts_league,wk1_pts_league
```

Every player present on the scraped board carries `pts_source = board`; everyone
else with a live projection carries `api`.

**`npm run export:boberto 2026`** prints how many rows matched a Sleeper id, how
many didn't, and how many AAV rows were dropped, then lists each unmatched name.
Its CSV header is:

```
player_id,player,position,team,bye_week,season_pts_half_ppr,aav_espn,aav_nffc,aav_yahoo,pass_yds,pass_tds,pass_ints,rush_yds,rush_tds,rec_yds,rec_tds,receptions,fumbles_lost,fg_0_39,pat_made,def_sacks,def_ints,def_fumble_recoveries,def_tds,def_safeties
```

**`npm test`** runs `src/boberto.test.ts` — name normalization plus the seven
`matchSleeperPlayer` cases (skill-player, defense-by-team, team-abbreviation,
position fallback, duplicate-name tie, nickname alias, unknown name). All should
pass.

## Gotchas

- **The `$` is scrape-only.** If `sleeper_proj_dollar` is blank across the board,
  you're missing `data/sleeper-board-{season}.csv` or scraped it into the wrong
  columns — nothing in the API will fill it. This is the single limitation called
  out in [01](01-projections-export.md).
- **CDN cache-busting is already handled.** `src/sleeper.ts` appends a
  `_cb=<epoch_ms>` param and sends `cache: "no-store"` on every request, so a
  re-run picks up fresh API data. Don't strip it — Sleeper's CDN otherwise serves
  stale copies, especially during a live draft.
- **Curate unmatched names, don't fuzzy-match.** When `export:boberto` prints a
  real player as unmatched, add an exact entry to `NAME_ALIASES` in
  `src/boberto.ts` (both sides in normalized form) and re-run. A fuzzy matcher was
  rejected on purpose: it trades these few known misses for silent wrong matches
  (see [02](02-boberto-twin.md)).
- **Board PTS beats API PTS by design.** For a board-listed player the export
  keeps the board's own PTS so rank/$/points stay one consistent snapshot; the
  API season number is only a fallback. Don't "fix" a small board-vs-API points
  gap — it's expected.
