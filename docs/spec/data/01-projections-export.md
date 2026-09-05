# 01 · Projections export (FAQ)

### What does this compute?

`scripts/export-projections.ts` produces `data/projections-{season}.csv` — the
season-points table every VORP number ultimately rests on. It fetches the
Sleeper player dump, the season-total projections and the weeks-1-3 projections,
joins the hand-scraped `data/sleeper-board-{season}.csv`, and writes one row per
draftable player with a single authoritative `season_pts_half_ppr` and a
`pts_source` flag saying where that number came from.

### Why not just dump the Sleeper API's season projection straight to CSV?

Because the API's `pts_half_ppr` and the draft board's own PTS come from
different Sleeper snapshots and disagree, and the board's auction dollars are
derived from the board's PTS, not the API's. Taking the API number for a
board-listed player would leave `sleeper_proj_dollar`, `sleeper_rank` and
`season_pts_half_ppr` describing two different snapshots. On the 2026 board Josh
Allen sits at `$52 / 351.5` board PTS while a same-day API call returned `361.5`
— close, but enough to make the dollar value and the point projection
inconsistent if you mixed them.

### How does it actually work?

Fetch everything in parallel, then join on `player_id`:

```
players, seasonProj, [wk1, wk2, wk3]  <- fetched via src/sleeper.ts (cache-busted)
board                                 <- loadBoard(): sleeper-board-{season}.csv, keyed by player_id
earlyWeeksPts[id] = sum of pts_half_ppr over weeks 1,2,3   (EARLY_WEEKS = [1,2,3])

eligible = players where position in {QB,RB,WR,TE,K,DEF} and active !== false

for each eligible player:
    board_entry = board.get(player_id)              # may be undefined
    pts        = board_entry.pts ?? seasonProj.pts_half_ppr
    pts_source = board_entry.pts !== undefined ? "board"
               : seasonProj.pts_half_ppr !== undefined ? "api"
               : ""                                  # neither had a number
```

The Sleeper fetches route through `src/sleeper.ts`, which appends a `_cb=<epoch_ms>`
cache-buster and sends `cache: "no-store"` on every request (see
`../../sleeper-api.md`), so a live re-run never serves a stale CDN copy.

### What is the `pts_source` rule, exactly?

The scraped board wins over the API for any player on it. `pts_source` is
`board` when the board carried a PTS for that `player_id`, `api` when it fell
back to the season endpoint, and the empty string when neither had a number.
The board is preferred because its PTS is the same snapshot that produced its
`$` and `rank` — so a board-sourced row keeps rank, dollars and points mutually
consistent.

### What's the output, precisely?

An eleven-column CSV: `player_id`, `player`, `position`, `team`,
`sleeper_rank`, `bye_week`, `sleeper_proj_dollar`, `season_pts_half_ppr`,
`pts_source`, `wk1_3_pts_league`, `wk1_pts_league`. One row per eligible player; board-only columns
(`sleeper_rank`, `bye_week`, `sleeper_proj_dollar`) are blank for players absent
from the board. The Python side (`python/vorp/csv_loader.py`) reads exactly one
of these columns — `season_pts_half_ppr` — and skips any row whose points cell
is blank.

### What does that look like in practice?

- **On the board:** a player the scrape covers takes the board's PTS and is
  tagged `board`, keeping his points consistent with his scraped `$` and `rank`.
- **Off the board:** an active fringe player with only an API projection takes
  `pts_half_ppr` and is tagged `api`, with the three board columns blank.
- **Worked example:** Jahmyr Gibbs (`player_id` 9221) is on the 2026 board at
  `rank 1, bye 6, $58`, board PTS `299.9`. Because a board PTS exists, the row
  emits `season_pts_half_ppr = 299.9` with `pts_source = board` — the board's
  number, not the API's — plus `wk1_3_pts_league = 61.11` summed from weeks 1-3
  and `wk1_pts_league = 20.27` for week 1 alone, both scored in league rules
  rather than read off the API's `pts_half_ppr`.

### What about a player with no board entry *and* no API projection?

`season_pts_half_ppr` is left blank and `pts_source` is the empty string —
**not** `0`. The wrong assumption is that a missing projection means zero points;
it means unknown, and `load_players_from_csv` drops the row (`not points`) rather
than fielding a phantom zero-point player against replacement level.

### What's the catch?

`sleeper_proj_dollar` is not available from any Sleeper API — it is computed
client-side only, in the draft board's React state, and must be hand-scraped
into `data/sleeper-board-{season}.csv` from a logged-in browser session (see
`../../sleeper-api.md`, "Auction value"). Run without that file and the script
still works, but `sleeper_rank`, `bye_week` and `sleeper_proj_dollar` come out
blank for everyone and every point falls back to `api` — it prints
`No board CSV at … — rank/bye/dollar columns will be blank.` and carries on.

### Why sum only weeks 1-3 into a separate column?

The early-season window is a coverage signal, not the pricing number. Sleeper
only publishes weekly projections for players expected to play, so at a thin
position the weeks-1-3 pool can list fewer bodies than the league has slots —
which is exactly the QB pool-exhaustion `../vorp/03-vorp-to-bid.md` flags. It
lives in its own `wk1_3_pts_league` column so it can be inspected without
disturbing the season points the engine prices on. `wk1_pts_league` carries
week 1 on its own, for the queue builder's comparison cards.

### Why are the weekly columns scored here instead of read off the API?

Because Sleeper's `pts_half_ppr` is not this league's scoring. It pays 6 for a
passing TD; both leagues here pay 4, so the API's number inflates every QB by
about four points a game — Jared Goff's week 1 reads 20.34 there and 17.0 in
the app. The season column does not have this problem, because it comes from
the hand-scraped board, which is already in league scoring; taking the API's
weekly number put two different scorings side by side in one row.

`scoreProjection` (`src/sleeper.ts`) fixes it by scoring the projected stat
line, which the same response carries, against the league's own
`scoring_settings`. Scoring keys and stat keys share a namespace, so it is a
dot product. The settings come from the snake league; the auction league scores
offence identically and differs only in `fum` and in kicker/defence rules,
neither of which reaches these columns.

### Does a re-run pick up fresh Sleeper data?

Yes for the API halves — players, season and weekly projections are re-fetched
cache-busted each run. No for the dollars: the board CSV is a point-in-time
snapshot with no API behind it, so its freshness is whenever you last scraped it
by hand. Commit it and re-scrape closer to draft day if values drift.

---

## Reference

**Depends on:** the Sleeper REST API via `src/sleeper.ts` (`fetchPlayers`,
`fetchSeasonProjections`, `fetchWeeklyProjections`, `fetchLeague`,
`scoreProjection`, `sleeperPlayerFullName`), the
hand-scraped `data/sleeper-board-{season}.csv`, and the endpoint contract in
`../../sleeper-api.md`. **Implemented in:** `scripts/export-projections.ts`
(`loadBoard`, `main`, `EARLY_WEEKS`), consumed on the Python side by
`python/vorp/csv_loader.py` (`load_players_from_csv`, which reads
`season_pts_half_ppr`). **Done when:** `npm run export:projections 2026` writes
`data/projections-{season}.csv` with the eleven-column header above, every
board-listed player carries `pts_source = board`, and `load_players_from_csv`
loads a `RosterFillPlayer` for every QB/RB/WR/TE/K/DEF row with a non-blank
points cell.

| Input | Description |
| --- | --- |
| `GET /players/nfl` | full player dump; filtered client-side to `{QB,RB,WR,TE,K,DEF}` and `active !== false` |
| `GET /projections/nfl/regular/{season}` | season-total projections; supplies `pts_half_ppr` |
| `GET /projections/nfl/regular/{season}/{week}` | weeks 1, 2, 3; stat lines scored into `wk1_3_pts_league` and `wk1_pts_league` |
| `GET /league/{league_id}` | the snake league's `scoring_settings`, which the weekly columns are scored with |
| `data/sleeper-board-{season}.csv` | hand-scraped `player_id,sleeper_rank,bye_week,sleeper_proj_dollar,sleeper_board_pts_half_ppr` |

| Output | Description |
| --- | --- |
| `data/projections-{season}.csv` | one row per eligible player, eleven columns |
| `season_pts_half_ppr` | the pricing number; board PTS if listed, else API `pts_half_ppr` |
| `pts_source` | `board`, `api`, or `""` — where `season_pts_half_ppr` came from |
| `sleeper_proj_dollar` / `sleeper_rank` / `bye_week` | board-only; blank for players off the scrape |
| `wk1_3_pts_league` | weeks-1-3 sum in league scoring; an early-season coverage signal |
| `wk1_pts_league` | week 1 alone in league scoring; shown on the queue builder's cards |
