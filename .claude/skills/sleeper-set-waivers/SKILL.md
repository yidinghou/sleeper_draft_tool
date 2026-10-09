---
name: sleeper-set-waivers
description: Submit a real waiver claim or free-agent add/drop through python/scripts/waiver_claim.py instead of clicking through the Sleeper UI. Use whenever the user wants to claim a player off waivers, pick up a free agent, or asks to "set waivers" / "do my waivers this week" for their real Sleeper league.
---

# sleeper-set-waivers

Claims a player through `python/scripts/waiver_claim.py`, which talks to
Sleeper's private GraphQL endpoint (`https://sleeper.com/graphql`) the same
way `draft_pick.py` does — the public v1 API has no write endpoints at all.
See that script's docstring for how the mutations were reverse-engineered
(downloading Sleeper's own public JS bundle and grepping it, never by
submitting a live request).

## Step 0: identify the league

The user has (at least) two real Sleeper leagues sharing this repo — see the
**Leagues** table in the root `README.md` for both league IDs and how to
tell them apart. Confirm which one before doing anything else; don't assume
`LEAGUE_CONFIG.league_id` (the auction league) is the right one just because
it's the default in `python/vorp/league/config.py` — `SNAKE_CONFIG` is a
different real league with its own roster and waivers. If it isn't obvious
from context (e.g. the user names a player who's only rostered in one of
them), ask.

## Step 1: figure out who to add (and drop)

- Trending adds, public and read-only: `GET https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=48&limit=50`.
- Cross-reference against `GET https://api.sleeper.app/v1/league/{league_id}/rosters`
  (union of every roster's `players` list) to filter to actual free agents in
  *this* league — a trending player leaguewide may already be rostered here.
- The league's own roster (`GET .../rosters` filtered to the seat whose
  `owner_id` matches the user, resolved via `league/config.py`'s `MY_USERNAME`
  against `GET .../league/{league_id}/users`) tells you if there's an open
  bench spot. **Always ask the user which player to drop if the roster is
  full** — that's their call, not one to make unilaterally, even when the
  add is obvious.

## Step 2: confirm the exact payload before sending

```bash
cd python
python3 scripts/waiver_claim.py ADD_PLAYER_ID --drop DROP_PLAYER_ID --bid N
```

No `--confirm` → dry run, prints the payload only. **Always show this dry run
to the user and get an explicit go-ahead before adding `--confirm`** — this
sends a real transaction against their real roster (FAAB budget, roster
spot), same stakes as a real trade or draft pick. Double check the player_id
actually matches the intended player (trending-list ids and roster ids look
similar; a mismatch silently claims/drops the wrong guy) — re-derive the id
from a fresh players lookup rather than trusting a remembered number.

## Step 3: get the auth token, without Claude ever seeing it

`--confirm` needs `$SLEEPER_TOKEN` or `~/.sleeper_token` (a long-lived JWT).
**Never try to extract this from the browser via javascript_tool or any
automation** — reading the app's session token, even to display it back to
the user, is blocked by the safety layer as credential handling, and trying
to route around that (e.g. printing it into the page instead of returning it
to the tool call) defeats the intent of the block, not just the letter of it.

Instead, walk the user through getting it themselves:
- **DevTools → Application → Local Storage → `https://sleeper.com` → `token`
  key**, copy the value, or
- **DevTools → Network → filter `graphql` → click a request → Headers →
  Request Headers → `authorization`**.

Then have them run themselves:
```bash
echo 'PASTE_TOKEN_HERE' > ~/.sleeper_token
```
Verify the file exists and looks like a JWT without printing it:
```bash
test -f ~/.sleeper_token && wc -c ~/.sleeper_token && head -c 10 ~/.sleeper_token
```

## Step 4: send it, then show the result

```bash
python3 scripts/waiver_claim.py ADD_PLAYER_ID --drop DROP_PLAYER_ID --bid N --confirm
```

A successful `submit_waiver_claim` response comes back `"status": "pending"`
with a `transaction_id` — it processes at the league's next waiver run, not
instantly. `league_create_transaction` (pass `--free-agent`) is instant
instead, for a player who has already cleared waivers.

## Not built yet

Cancelling a pending claim (`cancel_waiver_claim` mutation — the query shape
is already documented in `waiver_claim.py`'s module docstring, just not
wired into the script), and updating one already submitted
(`update_waiver_claim`, for changing the bid/settings). Add these the same
way if asked.
