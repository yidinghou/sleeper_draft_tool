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

Work the week in this order: **identify players → identify drops → find the
edge → set prices → submit.**

## Step 0: identify the league

The user has (at least) two real Sleeper leagues sharing this repo — see the
**Leagues** table in the root `README.md` for both league IDs and how to
tell them apart. Confirm which one before doing anything else; don't assume
`LEAGUE_CONFIG.league_id` (the auction league) is the right one just because
it's the default in `python/vorp/league/config.py` — `SNAKE_CONFIG` is a
different real league with its own roster and waivers. If it isn't obvious
from context (e.g. the user names a player who's only rostered in one of
them), ask.

Then check what's already in flight: `python3 scripts/check_waivers.py`
(read-only, needs `~/.sleeper_token`/`$SLEEPER_TOKEN`, defaults to both
leagues). The public v1 `GET /league/{id}/transactions/{week}` never returns
`pending` transactions, only resolved ones — it will silently look like "no
waivers in" even when the league's "My Waivers" panel shows several, so this
script (private GraphQL) is the only reliable read. A pending claim is a
soft preference, not a locked decision — surfacing a better candidate that
would replace it is fine, just say so and confirm before submitting a claim
that supersedes it.

## Step 1: identify players

`python3 scripts/waiver_targets.py --league-id LEAGUE_ID --week CURRENT_WEEK`
does this: pulls Sleeper's trending-add list, filters to actual free agents
in this league (cross-referenced against every roster's `players` list), and
prints a ranked table. `--week` is optional but enables the bye-based
INSURANCE tag in Step 2.

## Step 2: find the edge

`waiver_targets.py`'s table already tags each candidate — this *is* the
"why," don't re-derive it by eyeballing trending-add counts:
- **INSURANCE** — handcuffs one of your rostered players (same team/position,
  worse depth-chart slot), or covers an upcoming bye at a position you start.
- **STARTER** — real standalone role on their own team (depth-chart order 1
  or 2), independent of your roster.
- A candidate can carry both tags, one, or neither (a bare trending-add count
  with no tag is a speculative/momentum play, not a confirmed edge).

The `WHY` column also carries a Rotowire headline when one exists — read it,
but the tag + reason is the primary signal since it's computed straight from
Sleeper's own depth chart data, not just discourse. Depth-chart data can lag
real news (a promotion the beat writers know about before Sleeper updates
`depth_chart_order`); if the user flags a specific case where their own
knowledge disagrees with the tag, say so and treat their read as an
override rather than trusting the field blindly — but don't build a
standing override table for a case that hasn't come up.

## Step 3: identify drops

The end of `waiver_targets.py`'s output shows your roster fullness. If it's
full, **always ask the user which player to drop** — that's their call, not
one to make unilaterally, even when the add is obvious. Good drop candidates
tend to be the same shape as bad INSURANCE/STARTER hits on your own bench:
low depth-chart order on their own team, no bye-week or handcuff relevance to
anyone else on the roster.

## Step 4: set prices

`waiver_targets.py`'s output also prints `FAAB left: $N` for your roster
(from the league's real `settings.waiver_budget` minus your
`settings.waiver_budget_used` — the live FAAB pool, not
`LeagueConfig.budget`, which is that league's auction *draft* budget and
doesn't apply here). There's no bid-suggestion formula — sizing the bid
relative to that number and how much you want the player is the user's
judgment call, not something to compute for them.

## Step 5: submit

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

Once it's set:
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
