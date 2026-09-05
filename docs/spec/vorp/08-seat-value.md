# 08 · What one seat should bid (FAQ)

### What does this compute?

What a player is worth to **one seat**, and the most that seat may legally say
out loud. `04`'s blended price answers "what is he worth in this room"; this
answers "what is he worth to me, and can I even bid it". Two corrections to the
board price, applied in order: the seat's own roster changes the value, and the
seat's own budget caps the bid.

### Why isn't the board price the answer?

Because it is the same number for all twelve seats. A manager holding three
running backs values a fourth exactly as much as a manager holding none, which
is wrong for a reason that has nothing to do with taste: the fourth back
reaches no slot that scores points, so he adds nothing to that roster. The
board price also outruns the budget — it will happily advise $62 to a seat
holding $30.

### Why not just scale the board price by positional need?

Because "need" then becomes a second dial, and it has to be invented: how much
does a 2-of-3 RB seat discount, exactly? A multiplier also can't express the
case that actually matters, where a great player is still worth *something* to
a full position group because he displaces a starter. Need isn't an adjustment
to make to the value; it's what the value already is, once you measure it
against the right roster.

### How does it actually work?

A player is worth to a seat the points he adds to that seat's optimal starting
lineup, where the pool being seated is the seat's own players **plus a
freely-available body at every position**, so no slot is ever truly empty:

```
seat_vorp(seat, player) = lineup(bought + [player]) − lineup(bought)

lineup(roster) = points of the best assignment of `roster` + free agents
                 into the seat's starting slots
free agents    = one body per position, projected at replacement level,
                 in unlimited supply
```

The assignment is `../league/02-slot-assignment.md`'s matching, run over one
seat's slots — the same one `../league/03-seats-and-sales.md` already uses to
decide which of a seat's spots are open. Nothing about need is special-cased:
a player who out-scores nobody the seat can field finds no augmenting path
that improves the total, and the two lineups come back equal.

### Why put the free agents in the pool rather than scoring empty slots after?

Because the matching maximizes the **count** of players seated, not the points
on the field, and those are the same objective only while every slot is worth
the same when empty. They are not. A seat with nine players and ten slots has
several maximum matchings: leaving the SUPER_FLEX open is worth 214.8 (a free
quarterback fills it) while leaving the REC_FLEX open is worth 139.6 (a free
receiver), and both seat nine men, so the matching alone cannot choose between
them. Scoring the leftovers afterwards takes whichever one the fill happened to
return — on the 2026 board that priced an elite back at 160.3 points of value
instead of 109.8.

With the free agents in the pool every slot is filled, so the objective
collapses back to "total points of the seated set" — exactly the transversal
matroid `01-calculating-replacement.md` proves greedy points-descending
selection solves optimally. One pool per position covers every slot that
accepts it.

### Why impute a replacement body instead of leaving the open slot empty?

Because an empty slot makes a player worth his whole projection rather than his
margin, and margin is the founding claim of every model here. The vibe-code
prototype measured this: pricing against empty slots valued its 192 sold
players at $13,472 against $2,400 of real money. Against an imputed body, a
seat with an open RB slot values a back at exactly `points − replacement`,
which is his league VORP — so an empty seat agrees with the board price, and
only a seat that has actually bought something disagrees.

### What's the output, precisely?

Per seat per player: a value in points (`seat_vorp`, never negative), and a
whole-dollar bid. Dollars use the same league-wide exchange rate `04` prices
on — pool-after-floors over total league margin — so seat bid and board price
are the same unit and can be shown side by side:

```
bid = clamp(min_bid + floor(rate × seat_vorp),  max_bid(seat))
```

Floored, not rounded: rounding up would advise a bid the model has just called
too dear.

### What does that look like in practice?

- **Empty seat:** every open slot holds a replacement body, so every value is
  the league VORP and every bid is the board price. The model is invisible
  until someone buys something, which is the same way `../league/03` behaves.
- **Position group full:** a seat whose RB-, FLEX- and SUPER_FLEX-eligible
  slots are all spoken for values the next mediocre back at 0 and bids $1.
- **Upgrade:** the same seat still values a *great* back, because he displaces
  the worst starter he beats — just less than the room does. "Full" limits
  what a player is worth to a seat; it never zeroes it.
- **Worked example:** the 2026 board puts RB replacement at 137.9 and the
  exchange rate at $0.391/point. A 200-point back is worth 62.1 to the room,
  so the board price is `1 + floor(0.391 × 62.1)` = **$25**. To a seat holding
  two QBs, three RBs, two WRs and a TE — every RB-eligible slot filled, its
  weakest back in the flex at 160 — he displaces that back and is worth
  `200 − 160` = 40, so that seat's bid is `1 + floor(0.391 × 40)` = **$16**.

### What about a seat with only bench slots open?

Anyone who beats nobody in its lineup is worth 0 to it, and it bids the floor
on them. Bench slots are left out of the lineup on purpose: a benched player
scores nothing, so he adds nothing, and `04` already takes the position that
the bench is floor-priced. The wrong answer is scoring bench slots too, which
would quietly make a seat's seventh receiver worth real money.

What does **not** follow is that a full seat values nobody. A player good
enough to displace one of its starters is still worth the upgrade, bench or no
bench — it is the bench that has no value, not the seat.

### What about a seat with no roster spots left at all?

Its value for a player can still be positive — a full roster would genuinely
improve by swapping a starter out, and the lineup solve says by how much — but
its bid is 0, because it has nowhere to put him. Value and legality are
separate questions and this is the case that pulls them apart. Collapsing them
would hide the upgrade; keeping them apart means the budget cap is the only
thing that ever refuses a bid.

### What if a seat can't afford what it thinks a player is worth?

The bid is capped at `budget_left − (open_slots − 1) × min_bid` — its budget,
less a dollar held in reserve for every *other* spot it still has to fill,
which is `../league/03`'s `max_bid`. A seat with no open spots, or with too
little money to cover the floor, returns **0** rather than `min_bid`: "out" and
"can have him for a dollar" are different claims, and showing the second to a
manager whose roster is full advises a bid that cannot be made.

### What's the catch?

Seat values do not reconcile to the pool. `05`'s `reconciles` law — every
dollar in the room allocated exactly once — is a property of the board price
and cannot hold here: twelve seats each valuing the same player produce twelve
numbers, and their sum means nothing. So this model can never replace `04`, only
sit beside it. It also says nothing about what a player will actually *cost*,
which depends on the eleven other seats' willingness, not this one's.

### Does this hold up as the draft runs?

Yes, at two lineup solves per player per seat over ~10 starting slots. The
baseline solve is a fact about the position rather than the man, so it is
hoisted: one baseline per position per seat, then one solve per candidate.

---

## Reference

**Depends on:** `../league/03-seats-and-sales.md` for seats, open slots and
`max_bid`; `../league/02-slot-assignment.md` for the matching;
`01-calculating-replacement.md` for the bar and `04-blended-bar-pricing.md`
for the board price and exchange rate. **Implemented in:**
`python/vorp/seat_value.py` (`seat_vorp`, `seat_values`, `free_agents`,
`price_from_value`, `seat_bid`, `vorp_rate`), reusing
`python/vorp/league/roster_fill.py`'s `assign_to_slots` and
`python/vorp/league/teams.py`'s `Seat`/`seat_slots`/`max_bid`. Demonstrated by
`python/artifact/build_seat_value.py`, whose `--verify` re-solves every preset
against this model so the page's JavaScript port cannot drift from it.
**Done when:** no seat bid ever exceeds that seat's `max_bid` or its remaining
budget; a player who out-scores nobody the seat can field is worth exactly 0
and bids the floor; an opening seat's values equal league VORP player for
player; the lineup leaves open whichever slot a free body fills best; and
`data/blended-price-2026.json` and `data/draft-demo-2026-*.json` regenerate
byte-identical, since none of this touches the board price.

| Input | Description |
| --- | --- |
| `LeagueState`, `seat_id` | the seat's bought players, budget left and open slots |
| Points by player id | projections for both the seat's roster and the candidate |
| Replacement levels | per position, from the live league-wide fill |
| Exchange rate | dollars per margin point, from the same board solve |

| Output | Description |
| --- | --- |
| `seat_vorp` | points the player adds to this seat's starting lineup; `≥ 0` |
| `seat_bid` | whole dollars, `≥ min_bid` when biddable, `0` when the seat is out |
| Cap applied | `max_bid(seat)`, always the last step |
