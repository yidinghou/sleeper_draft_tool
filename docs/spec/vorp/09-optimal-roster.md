# 09 · The best affordable roster (FAQ) — WIP

> **Work in progress — not yet implemented.** `python/vorp/optimal_roster.py`
> doesn't exist yet, and this model spends against `07`'s board price
> (`price_board`), which is itself not yet implemented — see
> [`07 · Live draft board`](07-live-draft-board.md). Expect this spec to be
> revised once `07` and this model land.

### What does this compute?

Given **one seat's** remaining budget and open slots, and the current board
price of everyone still available, the *set* of players that buys that seat the
most starting-lineup points its money can still reach. `08` prices one player at
a time and never looks past the man on the block; this is the auction's
knapsack — the whole shopping list, not the next bid.

### Why isn't `08` (seat value) already the answer?

Because `08` answers "is *this* player worth it", one player, in isolation. It
can tell you a receiver adds 40 points to your lineup right now; it can't tell
you whether spending on him leaves you able to fill your other five slots, or
whether two cheaper players would buy more total points. Roster construction
under a budget is a question about the *set*, and no per-player number answers
it.

### Why is this a knapsack and not just "rank by value-per-dollar once"?

Because the value of a set is **not the sum of its players' values**. Starting
points come from the FLEX/SUPER_FLEX matching (`../league/02-slot-assignment.md`),
and a benched player scores nothing — so a second elite back can be worth far
less than the first, and a receiver who only displaces your weakest starter is
worth just the gap. The objective is `08`'s lineup solve re-run as the set
grows, never a fixed per-player figure summed up. That coupling is exactly what
makes it a budgeted matching rather than a sort.

### How does it actually work?

Greedy by marginal-points-per-dollar, in the same greedy-over-a-matroid idiom
the rest of the repo runs on:

```
loop:
  cap        = max_bid(seat)                 # budget, $1 reserved per OTHER open slot
  if cap < min_bid: stop                     # no slot, or no money past the floors
  candidates = unsold, unowned, priced players with price <= cap
  values     = seat_vorp(seat + picks so far, candidate)   # 08, re-solved
  buy        = argmax  values[p] / price[p]  (tie: higher value, then id)
  if values[buy] <= 0: stop                  # only bench depth left; worth 0
  picks += buy;  seat = seat.sell(buy)       # consume one slot + its price
```

Feasibility is free: `max_bid` (`../league/03-seats-and-sales.md`) already holds
a dollar for every other open slot, and `sell` consumes exactly one slot via the
same matching. Re-valuing against the roster-plus-picks-so-far is what carries
the non-additivity — every FLEX interaction is priced by the real lineup solve,
never assumed.

### Can I keep a position off the plan, or see the whole roster?

Two knobs on top of the core solve:

- **`exclude_positions`** drops those positions from consideration entirely.
  Their slots simply stay open (a free replacement body fills them in the lineup
  math), and the plan never spends a dollar there. Use it to keep a streaming
  position like DEF off the shopping list — you'd rather stream it week to week
  than pay for it at the draft.
- **`fill_all`** adds a second phase after the value buys: it names a cheap body
  for every slot still open, so the output is a *whole roster* rather than only
  the buys that move the lineup. Fills are chosen cheapest-first, then by margin
  over replacement (the best still-available flier at any position, not a pile of
  whoever has the highest raw total), and each adds ~0 starting points by
  construction. They're returned separately (`fills`, tagged `kind="fill"`) so
  they never masquerade as lineup upgrades. An excluded position's slot is left
  open even under `fill_all`.

### Is greedy optimal?

No — the exact knapsack is NP-hard, and this is an approximation. It is *exactly*
optimal when prices are flat (value-per-dollar collapses to value, and
greedy-by-value over slot eligibility is the transversal matroid the fill
already solves optimally), and stays within a tight bound of the brute-forced
optimum when prices vary. The test suite pins both on a board small enough to
enumerate. Greedy is chosen over an exact solver because it needs no new
dependency, recomputes fast enough to re-run on every pick, and reads the same
way as `01`/`08`.

### What does it spend against — and isn't that the catch?

It spends against the **current board price** (`04`/`07`) — so the output is
"the best roster reachable *if prices hold*", the same disclaimer `07` already
makes: a fair-value model re-solved on new information, not a forecast of what
the room will actually pay. The room sets the real cost. Feeding the plan the
live *residual* prices (which already reflect the drift the room has caused) is
what keeps it honest as the draft runs; a plan priced off frozen opening values
would be stalest exactly when the room is running hottest. This never replaces
the per-player board price — it sits on top of it, like `08`.

### What's the output, precisely?

A `RosterPlan`: the ordered `targets` (each with its price and the marginal
points it added when chosen), the `fills` that complete the roster under
`fill_all` (tagged `kind="fill"`, ~0 points each), the total `spend`, the
`reserve` held for still-open slots, `budget_left_after`, the lineup points
`before`/`after` and their `gain`, the resulting starting lineup, and how many
roster slots remain open. By construction `spend + reserve <= budget` and
`len(targets) + len(fills) <= open slots`.

### What does that look like in practice?

- **Empty seat:** every open slot imputes a free body, so opening values are
  league VORP and the plan buys the best value-per-dollar first — the same
  anchor `08` has.
- **Position group full:** once a seat's RB-, FLEX- and SUPER_FLEX-eligible
  slots are spoken for, another back adds 0 and is never targeted — unless he's
  an *upgrade* on the weakest starter, in which case he's worth exactly the gap
  and may still make the plan.
- **Down to bench:** when every affordable player adds 0 startable points, the
  plan stops and reports the leftover as "N slots at `$1`" rather than burning
  money on bench depth the lineup can't use.

### What's the catch?

Two. First, greedy is an approximation, not the guaranteed optimum (above).
Second — and this is the real one — the plan is only as good as the prices it's
handed, and in a live auction those are projections the room is actively
falsifying. Read it as a *planning aid* ("here's the best roster still within
reach at fair value"), not an oracle for the next bid. And like `08`, it does
not reconcile to the pool: it's one seat's plan, and twelve seats' plans don't
sum to anything.

---

## Reference

**Depends on:** `08-seat-value.md` for the per-player lineup value (`seat_vorp`,
`seat_values`, `free_agents`, `_lineup_points`); `../league/03-seats-and-sales.md`
for `max_bid`, `sell` and open slots; `04`/`07` for the board prices it spends
against. **Implemented in:** `python/vorp/optimal_roster.py` (`plan_roster`,
`RosterPlan`, `Target`), reusing `python/vorp/seat_value.py` and
`python/vorp/league/teams.py`. Printed by `python/scripts/optimal_roster.py`.
**Done when:** for a mid-draft state no plan's `spend` exceeds the seat's
budget, `spend + reserve <= budget`, `len(targets) <= open slots`, and
`points_after >= points_before`; on a flat-price board small enough to
brute-force, greedy equals the true optimum, and with varied prices it stays
within a tight bound of it.

| Input | Description |
| --- | --- |
| `LeagueState`, `seat_id` | the seat's bought players, budget left and open slots |
| Player pool | `RosterFillPlayer`s to shop from — the board `04`/`07` prices |
| Prices | `{player_id: board price}`; an unpriced player is never a target |
| Replacement levels | per position, imputed into each open slot, exactly as `08` |

| Output | Description |
| --- | --- |
| `targets` | the players to buy, each with price and marginal points at purchase |
| `fills` | cheap bodies that complete the roster under `fill_all`; ~0 points each |
| `spend` / `reserve` | dollars spent; dollars held for still-open slots |
| `points_before` / `after` / `gain` | starting-lineup points, and what the plan adds |
| `lineup_ids` | the real players seated in the resulting best lineup |
| Feasibility | `spend + reserve <= budget`, `len(targets) <= open slots` |
