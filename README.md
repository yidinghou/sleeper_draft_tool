# sleeper_draft_tool

Sleeper draft tool — projections export and draft polling.

## Features

- **Projections export**: fetch player data and season/weekly projections from Sleeper, combine with manually scraped auction values, write to CSV.
- **Draft polling**: (coming soon) poll a live Sleeper draft and stream state updates.

## Setup

```bash
npm install
```

## Usage

### Export projections

```bash
npm run export:projections 2026
```

Outputs `data/projections-2026.csv` with columns: `player_id`, `player`, `position`, `team`, `sleeper_rank`, `bye_week`, `sleeper_proj_dollar`, `season_pts_half_ppr`, `pts_source`.

`pts_source` is `board` when the points came from the scraped draft board (preferred — same snapshot as the auction dollar values, so rank/$/pts are internally consistent) or `api` when falling back to the live `/projections/nfl/regular/{season}` endpoint for players not on the scraped board.

To include auction values (`sleeper_proj_dollar`, `sleeper_rank`, `bye_week`, `sleeper_board_pts_half_ppr`), manually scrape them from a logged-in Sleeper draft board into `data/sleeper-board-2026.csv` with columns: `player_id,sleeper_rank,bye_week,sleeper_proj_dollar,sleeper_board_pts_half_ppr`. This file is a point-in-time snapshot (Sleeper computes $ and its board PTS client-side only, no API) — committed to the repo so it doesn't need re-scraping every run, and re-scraped by hand closer to draft day if values drift.

### Leagues

Two real leagues share this tool (projections, VORP math) but are otherwise
separate — **always confirm which one before submitting anything** (a
waiver claim, a pick, etc.), never assume the default:

| | Auction league (`LEAGUE_CONFIG`) | Snake league (`SNAKE_CONFIG`) |
|---|---|---|
| Sleeper name | "L13 2026 12-Team SF Half-PPR" | "One league to Rule them all" |
| League ID | `1372724723108036608` | `1386051970791378944` |
| Teams | 12, superflex | 10, single QB |
| Draft type | Auction | Snake |
| 2026 draft ID | `1372724723120631808` (`https://sleeper.com/draft/nfl/1372724723120631808`) | looked up fresh each season, see below |

Both configs live in `python/vorp/league/config.py`. Draft IDs are looked up
via `GET /league/{league_id}/drafts` — Sleeper mints a new one every season,
so only the auction league's 2026 id is hardcoded above; don't assume it
carries over to next year.

## Running tests

```bash
npm test
```
