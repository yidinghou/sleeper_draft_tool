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

Outputs `data/projections-2026.csv` with columns: `player_id`, `player`, `position`, `team`, `sleeper_rank`, `bye_week`, `sleeper_proj_dollar`, `season_pts_half_ppr`, `week1_pts_half_ppr`, ...

To include auction values (`sleeper_proj_dollar`, `sleeper_rank`, `bye_week`), manually scrape them from a logged-in Sleeper draft board into `data/sleeper-board-2026.csv` with columns: `player_id,sleeper_rank,bye_week,sleeper_proj_dollar`.

## Running tests

```bash
npm test
```
