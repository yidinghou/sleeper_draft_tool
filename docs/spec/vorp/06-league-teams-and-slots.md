# 06 · League, teams and slots (FAQ)

### What does this compute?

The league's roster demand as an explicit list of **slots** — one object per seat per
roster spot — together with the money behind each seat. Every model in `01`–`05` is a
fill over this list; this spec is the substrate they all stand on.

### Why not per-team counts multiplied by `teams`?

Because a count can't express a single sale. This league wants 2 RB per team, so the
fill builds `2 × 12 = 24` RB slots — but 23 is not a number the per-team template can
hold, and dividing back down gives `23 // 12 = 1`, which claims all twelve seats just
filled a running back. On the real 2026 board that turns one sale into twelve: the
priced pool drops 192 → 180 and RB replacement level jumps 137.9 → 154.5. With real
slots the same sale gives 192 → 191 and leaves replacement level at 137.9, which is
correct — removing the best back *and* one back-shaped slot leaves the marginal back
exactly where he was.

### So how does it actually work?

A `Seat` per team holds the roster template, its remaining budget, and the players it
has bought. `LeagueState` is the seats plus the league config, and it answers three
questions the models need:

```
open slots = every seat's unfilled slots, unioned into one flat list
pool       = Σ each seat's remaining budget
spots left = len(open slots)
```

That flat list is already exactly what `solve_optimal_fill` takes, so the fill itself
doesn't change at all — it is handed a shorter list. Pre-draft the union is identical
to the old `count × teams` expansion; each sale removes exactly one slot from it and
the sale price from the pool.

### How does a seat know which of its slots a player fills?

By running the same bipartite matching over that one seat's slots. `01`'s fill
already computes which slot each player was seated in and then throws it away; this
model keeps it. The wrong answer, and the tempting one, is a greedy rule — take a
concrete slot, else a flex, else the bench — because it is order-dependent: a seat
that buys three receivers and then a back can end up with a different open-slot set
than a seat that bought the same four players in the other order.

### What's the output, precisely?

The slot list, each slot tagged with its owning seat. Per seat: which slots are still
open, the budget left, and a max bid of `budget_left − (open_slots − 1) × min_bid`.
Per league: the pool, the spots left, and the same per-position capacity the fill has
always consumed.

### What does that look like in practice?

- **Opening bell:** 12 seats × 16 spots = 192 slots and a $2400 pool, which is where
  `data/blended-price-2026.json`'s `counts.drafted` has always come from.
- **A seat fills up:** its remaining slots leave the union, so the league's demand at
  those positions falls and every bar behind them moves accordingly.
- **A seat spends down:** its max bid falls faster than its budget, because every
  still-open spot has to keep a dollar in reserve.
- **Worked example:** seat 4 buys a running back for $60. The league is left with 191
  slots and a $2340 pool; seat 4 has $140, 15 open spots, and a max bid of
  `140 − 14 × 1` = **$126**.

### What about a seat that has run out of money but still has open spots?

Its slots stay in the fill. A seat with $3 and three spots is still going to put three
bodies on its roster, so that demand is real and the players who fill it still have to
clear a bar. The wrong answer is dropping those slots as unbuyable, which shrinks
league-wide demand and lifts every replacement level in the league.

### What does this let us delete?

`LeagueConfig.plays_positions`. That field exists only because the old residual
config modelled consumed slots by zeroing counts, which made a position whose
starting slots were all spoken for look like one the league never plays — so it had
to carry the original list forward to stop bench eligibility collapsing. When slots
are objects the template never shrinks, only the open set does, and
`draftable_positions()` can no longer lie.

### What's the catch?

Seats are only as real as the feed tells us. A sale has to name a buyer, and Sleeper's
picks carry `roster_id` while manual entry doesn't — so an unattributed sale goes to a
synthetic seat. The league aggregate stays exact either way (the slot and the money
leave regardless), but that seat's own budget and max bid become fiction, and so do
the readouts of whichever real seat actually bought the player.

### Does this hold up as the draft runs?

Yes, one sale at a time, which is the whole point — league granularity is what `07`
needs to reprice per pick. Cost is linear: the union is rebuilt per sale and the
per-seat matching runs over one seat's 16 slots, not the league's 192.

---

## Reference

**Depends on:** nothing upstream — this is the substrate `01`–`05` build on.
**Implemented in:** `python/vorp/league_state.py` (`Seat`, `LeagueState`), with the
roster template staying in `python/vorp/league_config.py` and the slot assignment
exposed from `python/vorp/roster_fill.py`; consumed by
`python/vorp/replacement_level.py` and `python/vorp/last_rostered.py`. **Done when:**
the opening slot list has the same per-position capacity as the expansion it
replaces, `data/blended-price-2026.json` regenerates byte-identical, and one sale
removes exactly one slot and its price from the pool.

| Input | Description |
| --- | --- |
| Roster template | `starting_slots`, `flex_slots`, `bench_slots` — **per seat**, unchanged |
| `teams`, `budget`, `min_bid` | how many seats, and what each one starts with |
| Sales | `(player_id, position, amount, seat_id)` — `seat_id` optional |

| Output | Description |
| --- | --- |
| Open slot list | flat, one entry per unfilled spot, tagged with its seat |
| Pool | Σ remaining seat budgets; `teams × budget` pre-draft |
| Spots left | length of the open slot list; 192 pre-draft for this league |
| Per-seat state | budget left, open slots, max bid |
| Per-position capacity | slots accepting a position — what the fill reads |
