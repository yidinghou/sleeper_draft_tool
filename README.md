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

### League defaults

- League ID: `1372724723108036608`
- Draft ID (2026 season): `1372724723120631808` (draft board: `https://sleeper.com/draft/nfl/1372724723120631808`)

Note: the draft ID is looked up via `GET /league/{league_id}/drafts` — it's not the same as the league ID and Sleeper generates a new one each season.

## Running tests

```bash
npm test
```
