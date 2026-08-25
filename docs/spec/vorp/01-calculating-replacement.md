# 01 · Calculating replacement level (FAQ)

### What does this compute?

Replacement level: the score of the best player still available for
free at each position. `VORP = player's points − replacement level`.

### Why not a fixed flex ratio, like 60% RB / 40% WR?

Because the split isn't fixed — it changes every year with how deep
each position is. A ratio frozen from last year can't see a strong TE
class stealing flex slots from RBs.

### So how does it decide who gets a flex slot?

It solves, not decides in advance. Pool every team's slots (starting +
flex) and every player on the board, and find the highest-scoring
lineup the whole league could field if everyone drafted optimally at
once. Whoever the solve lands in a flex slot claims it.

### And replacement level?

Whoever's left over at each position once the solve is done — no
formula, no percentage.

### What does that look like in practice?

- **Deep TE class:** 25th-best TE outscores 25th-best RB → some flex
  slots go to TEs, TE replacement level drops.
- **Weak TE class:** no flex slots go to TE → replacement level is just
  the next TE after the starting slots.
- **Worked example:** 12 teams, 1 TE starter each, one WR/TE flex, all
  flex claimed by WRs → replacement level is the 13th-best TE. Board of
  220, 200, … 141 (12th), 140 (13th) → replacement level = 140.

### What about a position with no slot at all, like K?

No kicker is ever selected — no concrete slot, not flex-eligible
either. Output is *unreachable*, not 0. Zero means "worth nothing above
a real baseline." Unreachable means there's no baseline to measure.

### What's the catch?

It assumes optimal drafting. Real managers are often more cautious
about which position they'll flex than the solve is. Treat the output
as what the market *should* look like, not a forecast.

### Does it update live, during a draft?

Yes, for free. Rerun the same solve against whoever's left on the board
after each sale.

---

## Reference

**Depends on:** league config (`python/vorp/league_config.py`), the board of
projected points. **Implemented in:** `python/vorp/replacement_level.py`
(matching logic in `python/vorp/roster_fill.py`). **Done when:** on a
fixture board, the optimal fill picks the right flex players, and
replacement level equals the best player left outside that selection.

| Input | Description |
| --- | --- |
| Slots | `teams × (concrete + flex slots)`, from league config |
| Players | every board player, with position and points |
| Eligibility | own position's slot, or any flex slot it qualifies for |
| Objective | maximize total points across all filled slots |

| Output | Description |
| --- | --- |
| Selected set | which players are chosen, and which slot each fills |
| Replacement level, per position | best player not in the selected set |
