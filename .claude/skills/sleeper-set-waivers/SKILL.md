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

**This skill's job is to help the user work through their own opinions on
players, never to compute a recommendation for them.** The only mechanical
signal it uses is raw facts (who's a free agent, bye weeks, depth-chart
order, FAAB left) — no scoring, no tags, no ranked list claiming to know
who's worth adding or dropping. The actual judgment lives in the user's own
notes, which this skill helps them keep current.

## Step 0: identify the league

The user has (at least) two real Sleeper leagues sharing this repo — see the
**Leagues** table in the root `README.md` for both league IDs and how to
tell them apart. Confirm which one before doing anything else; don't assume
`LEAGUE_CONFIG.league_id` (the auction league) is the right one just because
it's the default in `python/vorp/league/config.py` — `SNAKE_CONFIG` is a
different real league with its own roster and waivers. If it isn't obvious
from context (e.g. the user names a player who's only rostered in one of
them), ask.

This also picks which notes file the rest of the session reads/writes:
- `python/data/notes/priors-auction.md` for `LEAGUE_CONFIG`
- `python/data/notes/priors-snake.md` for `SNAKE_CONFIG`

A session that touches both leagues just moves between the two files as it
moves between leagues — there's no cross-league sharing, since roster needs
and FAAB differ.

Then check what's already in flight: `python3 scripts/check_waivers.py`
(read-only, needs `~/.sleeper_token`/`$SLEEPER_TOKEN`, defaults to both
leagues). The public v1 `GET /league/{id}/transactions/{week}` never returns
`pending` transactions, only resolved ones — it will silently look like "no
waivers in" even when the league's "My Waivers" panel shows several, so this
script (private GraphQL) is the only reliable read. A pending claim is a
soft preference, not a locked decision — surfacing a better candidate that
would replace it is fine, just say so and confirm before submitting a claim
that supersedes it.

## Step 1: load priors and see what changed

`Read` that league's notes file. It's one `##` section per player, freeform
prose, the user's own running thesis — e.g. "TD threat even as volume dips,
buy the touchdown regression" for a player they're holding, or "breakout
watch behind an injury, want to see next week's volume before committing
FAAB" for a free agent they're tracking.

For every player the user names this session (someone they're weighing
whether to drop, hold, or pick up), show them their existing note if one
exists, and ask directly: **has anything changed since last time?** This is
a conversation, not a form — let them talk through it in their own words.
A player with no existing section is just a new one to add.

As soon as the user gives you something new for a player, **update that
`##` section in place right away** (`Edit`) rather than waiting until the
end of the session — git history on the file is the changelog, so there's
no need to keep old text inline or version anything by hand.

## Step 2 (optional): discover fresh candidates

If the user wants to see what's out there rather than just discuss players
they already have opinions on:

```
python3 scripts/waiver_targets.py --league-id LEAGUE_ID
```

This pulls Sleeper's trending-add list, filters to actual free agents in
this league, and prints **facts only** — position, team, bye week, Sleeper's
own depth-chart order, and any Rotowire headline — plus your current bench
(also facts only) and FAAB left. There is no tag or ranking column anymore;
treat this purely as a prompt for "does anything here deserve a note?", not
a recommendation. If the user wants outside intel on a specific name (a
podcast take, a beat-writer report), that's fine to go dig up, but fold what
you find straight into that player's note in Step 1 rather than keeping a
separate sourced-research document.

## Step 3: talk it through

With notes current for everyone in play, walk through the actual decision
with the user in plain language — what their note says, what's changed,
what the tradeoff is between the players they're weighing. **Always let the
user land on the add, the drop, and the bid themselves** — present the
considerations, don't collapse them to a pick on their behalf, even when the
choice looks obvious.

## Step 4: submit

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

After submitting (or deciding to hold/pass), update the relevant player
notes one more time with the outcome and why — that's next week's starting
point.

## Not built yet

Cancelling a pending claim (`cancel_waiver_claim` mutation — the query shape
is already documented in `waiver_claim.py`'s module docstring, just not
wired into the script), and updating one already submitted
(`update_waiver_claim`, for changing the bid/settings). Add these the same
way if asked.
