# Sleeper API Reference

## Overview

Sleeper exposes a public, read-only REST API at `https://api.sleeper.app/v1`. **No authentication required** — all endpoints return data accessible to any client.

## Base URL and HTTP conventions

- Base: `https://api.sleeper.app/v1`
- No auth headers, no API key, no session token.
- **Cache-busting**: Sleeper's CDN caches aggressively. All requests should append a cache-buster query parameter:
  ```
  ?_cb=<epoch_ms>
  ```
  where `<epoch_ms>` is the current Unix timestamp in milliseconds (e.g., `?_cb=1724454000123`).
  - Combined with `cache: "no-store"` on the fetch, this defeats both browser and CDN caches.
  - Without it, responses may be stale by hours, especially `/draft` endpoints during live auctions.

## Endpoints

### Player data

#### `GET /players/nfl`

Full dump of all NFL players, unfiltered. ~5–10 MB JSON. No pagination.

**Response shape:**
```json
{
  "4623": {
    "player_id": "4623",
    "first_name": "Patrick",
    "last_name": "Mahomes",
    "full_name": "Patrick Mahomes",
    "position": "QB",
    "team": "KC",
    "status": "Active",
    "active": true,
    "years_exp": 5,
    ...
  },
  ...
}
```

**Filtering:** Client-side. Typically filter to `position` in `{QB, RB, WR, TE, K, DEF}` and `active !== false`.

### Projections

#### `GET /projections/nfl/regular/{season}`

Season-total projections for a given year.

**Response shape:**
```json
{
  "4623": {
    "player_id": "4623",
    "pts_ppr": 325.5,
    "pts_half_ppr": 287.2,
    "pts_std": 251.8,
    "adp_2qb": 3.1,
    ...
  },
  ...
}
```

**Scoring formats available:**
- `pts_ppr`: points per reception.
- `pts_half_ppr`: 0.5 points per reception.
- `pts_std`: standard (no bonus for receptions).

#### `GET /projections/nfl/regular/{season}/{week}`

Per-week projections. `week` is 1–17 (or more if playoffs are included that year).

**Response shape:** same as season projections, but points are per-week.

### Draft state

#### `GET /draft/{draft_id}`

Metadata and in-flight auction state for a single draft.

**Response shape:**
```json
{
  "draft_id": "...",
  "league_id": "...",
  "season": 2026,
  "type": "auction",
  "status": "in_progress",
  "settings": {
    "teams": 10,
    "budget": 200,
    "slots": {
      "QB": 1,
      "RB": 2,
      "WR": 3,
      "TE": 1,
      "K": 1,
      "DEF": 1,
      "BENCH": 5
    },
    "auction": true,
    "auction_start_time": 1724454000000,
    ...
  },
  "draft_order": ["user_id_1", "user_id_2", ...],
  "metadata": {
    "nominated_player_id": "4623",
    "nominating_slot": 1,
    "highest_offer": 42,
    "offering_slot": 5,
    "last_action_at": 1724454123456,
    ...
  },
  ...
}
```

**Key fields:**
- `draft_id`: unique draft identifier.
- `type`: `"auction"`, `null` (snake draft), or `"linear"` (linear/dispersal).
- `status`: `"not_started"`, `"in_progress"`, `"complete"`.
- `metadata.nominated_player_id`: currently on the block (or `null`).
- `metadata.nominating_slot`: which seat nominated this player (1-indexed by draft order).
- `metadata.highest_offer`: current high bid amount (string, e.g., `"42"`).
- `metadata.offering_slot`: which seat is currently holding the high bid (1-indexed by draft order).
- `draft_order`: array of `user_id`s in draft order; the index is the seat (1-indexed in `nominating_slot` and `offering_slot`).

**Poll cadence:** poll this endpoint **every 1–3 seconds** during a live auction. Lightweight request; safe to poll frequently.

#### `GET /draft/{draft_id}/picks`

All completed picks in the draft, in order.

**Response shape:**
```json
[
  {
    "draft_id": "...",
    "draft_slot": 1,
    "pick_no": 1,
    "round": 1,
    "picked_by": "user_id",
    "roster_id": 1,
    "player_id": "4623",
    "is_keeper": false,
    "metadata": {
      "amount": "51",
      "player_id": "4623",
      "position": "QB",
      "team": "KC",
      "first_name": "Patrick",
      "last_name": "Mahomes",
      "slot": "1",
      "sport": "nfl",
      "status": "Active",
      "injury_status": "",
      "years_exp": 5,
      ...
    }
  },
  ...
]
```

**Key fields:**
- `pick_no`: 1-indexed pick order (global across all seats).
- `draft_slot`: 1-indexed seat/round-order position.
- `player_id`: the player picked.
- `metadata.amount`: price paid (string; parse as `int`).
- `metadata.{position,team,first_name,last_name}`: fallback player identity (may differ from the `/players/nfl` entry if the player's status changed mid-season).

**Poll cadence:** poll less frequently (every 5–10 seconds), or only when the `/draft/{id}` metadata fingerprint changes (see polling pattern below).

### League and user data

#### `GET /league/{league_id}`

League metadata (settings, roster slots, etc.).

#### `GET /league/{league_id}/users`

Users in a league.

#### `GET /league/{league_id}/rosters`

Roster assignments for a league.

#### `GET /user/{username}`

User profile by username. Returns `{ "user_id": "...", "username": "..." }`.

---

## Polling pattern for live drafts

**Cheap poll (every tick):**
1. Call `GET /draft/{draft_id}` with cache-buster.
2. Extract a fingerprint: `last_picked|status|nominated_player_id|highest_offer|offering_slot|last_action_at`.
3. Compare to the previous fingerprint.

**Expensive poll (only on fingerprint change):**
- If the fingerprint changed, call `GET /draft/{draft_id}/picks` to fetch the updated picks.

This pattern keeps traffic low (~20 req/min for a 2-second poll interval) while staying current with auction action.

---

## Auction value (`sleeper_proj_dollar`)

**IMPORTANT:** Sleeper's estimated auction dollar value (`sleeper_proj_dollar`, or `$PROJ` on the draft board) is **not available from the API**. It is computed client-side only, in the browser's React state on the draft-board page.

**To obtain it:**
1. Open `https://sleeper.com/draft/nfl/{draft_id}` in a browser while logged in to your Sleeper account.
2. Use Claude in Chrome (or manual scraping) to extract the player-rank-to-dollar mapping from the virtualized draft-board list.
3. Write the result to `data/sleeper-board-{season}.csv` with columns: `player_id,sleeper_rank,bye_week,sleeper_proj_dollar`.
4. The projections-export script joins this CSV with API data on `player_id`.

**Example `sleeper-board-{season}.csv`:**
```
player_id,sleeper_rank,bye_week,sleeper_proj_dollar
4623,1,6,58
2580,2,10,57
4890,3,8,55
```

The `sleeper_rank` column should reflect the player's rank on the Sleeper draft board (which approximately tracks ADP, or `adp_2qb` if sorting by that), and `bye_week` is the player's bye week.

---

## Types

### SleeperPlayer
```typescript
interface SleeperPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  full_name: string;
  position: string;
  team: string;
  status: string;
  active?: boolean;
  years_exp?: number;
  [key: string]: any;
}
```

### SleeperProjection
```typescript
interface SleeperProjection {
  player_id: string;
  pts_ppr?: number;
  pts_half_ppr?: number;
  pts_std?: number;
  adp_2qb?: number;
  [key: string]: any;
}
```

### DraftPick
```typescript
interface DraftPick {
  draft_id: string;
  draft_slot: number;
  pick_no: number;
  round: number;
  picked_by: string;
  roster_id: number;
  player_id: string;
  is_keeper: boolean;
  metadata: {
    amount: string;
    player_id: string;
    position: string;
    team: string;
    first_name: string;
    last_name: string;
    slot: string;
    sport: string;
    status: string;
    injury_status: string;
    years_exp?: string;
    [key: string]: any;
  };
}
```

### Nomination
```typescript
interface Nomination {
  player_id: string | null;
  nominating_slot: number | null;
  highest_offer: string | null;
  offering_slot: number | null;
}
```
