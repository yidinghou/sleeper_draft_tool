# 02 · Slot assignment (FAQ)

### What does this compute?

The points-maximizing assignment of a pool of players to a pool of roster
slots, where each slot only accepts certain positions. It doesn't know what
league-wide replacement level or a seat's open roster spot is — it answers
one generic question, "given these players and these slots, who's selected
and where," and three different callers each hand it a different pool.

### Why not just take the top N players at each position?

Because flex slots are shared. Counting "top 2 RB, top 2 WR" separately
ignores that a flex slot might go to either — a strong tight-end class can
pull `SUPER_FLEX` slots away from running backs, and a per-position count
has no way to express that a slot's occupant depends on who else is
available. The wrong fix is a greedy rule (fill concrete slots first, then
flex, then bench): that's order-dependent, and a seat that buys three
receivers and then a back can end up with a different open-slot set than a
seat that bought the same four players in the other order.

### So how does it actually work?

Kuhn's algorithm: players are processed points-descending, and each one is
seated via an augmenting path — if every slot it's eligible for is taken,
it can bump an existing occupant into *their* other eligible slot instead of
losing its spot outright. Processing greedily by points is optimal here
because the set of simultaneously placeable players forms a transversal
matroid (see `../vorp/01-calculating-replacement.md`), so no player who
could be seated is ever left out by seating a higher-scorer first.

### What's the output, precisely?

`assign_to_slots` returns the full mapping, slot id to player id.
`solve_optimal_fill` is the same call with the slot ids dropped, just the
selected player set — what `01`/`02` in `../vorp/` read to compute a bar.
`summarize_by_position` turns a selected set into, per position: how many
players cleared it and the points of the best one who didn't — the number
every VORP calculation is actually keyed on.

### What does that look like in practice?

- **Flex steal:** a deep TE class outscoring RBs at the margin pulls
  `SUPER_FLEX` slots toward TE, so TE's `selected_count` rises and RB's
  falls, with no explicit rule saying so.
- **Order independence:** running `assign_to_slots` on the same players and
  slots in a different input order returns the identical mapping, because
  the algorithm sorts by points internally before assigning.
- **Worked example:** 12 teams, 1 TE starting slot each and one shared
  WR/TE flex, all claimed by WRs → the TE `PositionFillSummary` has
  `selected_count = 12` and `level_points` equal to the 13th-best TE's
  score.

### What happens when the player pool runs out before the slots do?

`pool_exhausted=True` and `level_points=None` — there's no "best one who
didn't make it" to read a bar off, because everyone at that position got
seated. Callers must not treat that as a bar of 0; a 0 means "worth nothing
above a real baseline," and there is no baseline here because the pool was
too short, not because the position is deep.

### What's the catch?

It optimizes for total points across the whole pool, which is the right
objective for a league-wide bar but says nothing about what any individual
manager would actually do with imperfect information about who else is
drafting what. Real managers don't solve a global matching before every
pick.

### Does this hold up at scale, or per-seat as well as league-wide?

Yes to both — the same function runs over 192 league-wide slots pre-draft or
16 slots for one seat (`03-seats-and-sales.md` uses it both ways), and cost
scales with the size of the pool it's handed, not with which caller is
asking.

---

## Reference

**Depends on:** nothing upstream — pure matching over whatever `RosterFillPlayer`/`Slot`
pool it's given. **Implemented in:** `python/vorp/league/roster_fill.py`
(`assign_to_slots`, `solve_optimal_fill`, `summarize_by_position`).
**Done when:** the selected set is order-independent of input order, and
`summarize_by_position` correctly distinguishes a position with no slot at
all (`reachable=False`) from one whose pool ran out (`pool_exhausted=True`).

| Input | Description |
| --- | --- |
| Players | `RosterFillPlayer(player_id, position, points)` |
| Slots | `Slot(id, eligible_positions, seat_id=None)` — `seat_id` is opaque to the matching |
| Positions | which positions to summarize a bar for |

| Output | Description |
| --- | --- |
| `assign_to_slots` | `{slot_id: player_id}` for every filled slot |
| `solve_optimal_fill` | the selected player id set, slot ids dropped |
| `PositionFillSummary` | per position: `reachable`, `level_points`, `selected_count`, `pool_exhausted` |
