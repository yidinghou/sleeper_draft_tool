# 04 · Blended-bar pricing (FAQ)

### What does this compute?

One auction price per drafted player, out of a single pool of
`teams × budget`. Each player is measured against a bar that blends his
position's replacement level (`01`) and last-rostered level (`02`), and the
whole budget is apportioned by the resulting margin.

### Why not blend the two dollar figures `03` produces?

Because that measures different players against different bars — starters
against replacement level, bench-only picks against the last-rostered level —
and nothing forces those two curves to meet where the populations touch. On
the real 2026 board that gap put a worse player above a better one: Cam Ward
(214.8 pts, bench) priced above Bryce Young (224.6 pts, starter). Blending the
bars instead of the prices removes the failure mode rather than tuning around
it.

### So how does it actually work?

Every position gets a bar that slides with the player being priced:

```
w(p)   = w_floor + (1 - w_floor) · t
bar(p) = w(p) · replacement_level + (1 - w(p)) · last_rostered_level
margin = max(0, points - bar(p))
```

`w_floor` is **the one dial, and a human sets it** — on the slider in the
exported page. Everything else in that formula is fixed by the shape of the
model, so there is exactly one number to argue about.

`t` ramps from 0 to 1 **linearly in points**, from the last-rostered level up
to the full-weight point — the points of the starter sitting
`FULL_WEIGHT_SHARE` (0.75) down that position's ranking. Above that point `t = 1`,
so the top 75% of starters are measured against replacement level and nothing
else, exactly as a starter should be. Below it the bar slides toward the
last-rostered level, so a marginal starter and a strong bench pick land on one
continuum instead of falling off a cliff between two lenses. The margins are
apportioned with `apportion_with_floor`, reserving `min_bid` per player, so the
column sums to exactly `teams × budget`.

### Why linear in points rather than by rank?

Because that's what keeps price rising with points. Margin is
`points - bar(points)`, which rises only while `d(bar)/d(points) ≤ 1`; ramping
in points makes that derivative the constant
`(replacement - last_rostered) / ramp_span`, so the condition reduces to "the
ramp spans at least the gap between its two bars." Ramping by rank makes the
slope explode wherever players bunch tightly in points, which is exactly the
bottom of every position's board.

### What's the output, precisely?

A whole-dollar price `>= min_bid` for every player the full-roster fill
selects, and no entry at all for anyone else. A position the template never
plays (K here) is absent, as in `01`–`03` — unreachable, not `$0`.

### What does that look like in practice?

- **Elite starter:** sits above the full-weight point, so his bar is
  replacement level and the ramp never touches him.
- **Marginal starter and top bench pick:** both sit inside the band, priced
  on the same sliding bar, so neither can leapfrog the other.
- **Streamed position (DEF):** `02` pins its two levels equal, so the ramp
  collapses to a point and every defense is priced off one bar.
- **Worked example:** 12 teams, $200, the dial at `w_floor = 0.5`. TE's levels are 129.5 and 83.9, and the starter at the 75%
  mark scores 136.4, so the band runs 83.9 → 136.4. Brenton Strange
  (129.5 pts) sits at `t = 0.869`, giving `w = 0.934` and a bar of 126.50 — a
  margin of **3.00**, below Dalton Kincaid's 3.62 rather than above it, which
  is the inversion `03`'s bid produced.

### What about a position whose starting slots are all consumed mid-draft?

It has no replacement level, so the ramp collapses onto the last-rostered
level and it is priced as what it has become — a pure bench position. The
wrong answer, and the one an earlier version gave, is to drop the position
entirely and price every remaining player there at nothing.

### Why is there only one dial?

Because two dials that both move prices in the same direction give a reader
two ways to say the same thing and no way to tell which one was wrong.
`FULL_WEIGHT_SHARE` sets where the blended band *starts* and `w_floor` sets
how far the bar slides *inside* it — tune both and any given price has many
explanations. So `FULL_WEIGHT_SHARE` is a constant of the model's shape, in
`python/vorp/models.py`, changed by editing the model. `w_floor` is the dial,
it is set by a human on the slider, and the exported page has exactly one.

### What's the catch?

The ramp is a judgement, not a derivation. `FULL_WEIGHT_SHARE = 0.75` is a
round number nobody measured, and `w_floor = 0.5` was picked because it
happens to land the starter/bench split and the market error near their best
on the 2026 board — a different board could put it elsewhere. The shape is
provably monotonic at every dial setting, but "which setting" is calibration,
and it is the part of this module most likely to be wrong. That is exactly
why the dial is exposed rather than baked in: the human moves it and watches
the numbers, instead of trusting a default nobody can defend.

### Why is QB's last-rostered level floored?

Pooling QBs against QBs alone made QB's last-rostered level 50.9 while every
other position sat above 77. In a superflex league nobody rosters the 50th
quarterback when a better receiver is free for the same slot, so `02` floors
each flex-eligible position at the worst level among its flex peers — lifting
QB to 77.2 and leaving the rest untouched.

---

## Reference

**Depends on:** `01-calculating-replacement.md`'s replacement level and
selected set, `02-value-over-last-rostered.md`'s last-rostered level (flex-peer
floor included) and selected set, league config (`python/vorp/league_config.py`).
**Implemented in:** `python/vorp/models.py` (`progressive_blend`, sharing
`apportion_with_floor` from `python/vorp/bid_value.py`); exported by
`python/scripts/blended_price.py`. **Done when:** on a hand-written fixture the
price-blending approach inverts a barely-clearing starter against a strong
bench pick and bar-blending does not, prices sum to exactly `teams × budget`,
and the `monotonic` and `ramp-slope` laws in `05` both pass at every `w_floor`.

| Input | Description |
| --- | --- |
| Replacement level, per position | from `01` — the top of the ramp's bar range |
| Last-rostered level, per position | from `02` — the bottom, flex-peer floored |
| Full-roster selected set | from `02` — exactly who gets priced |
| `w_floor` | **the one dial, set by a human**: blend weight at the last-rostered level; 1.0 is pure VORP, ships at 0.5 |
| League config | `teams`, `budget`, `min_bid` |

| Output | Description |
| --- | --- |
| Price, per drafted player | whole dollars `>= min_bid`; absent for anyone undrafted |
| Reconciliation | the column sums to exactly `teams × budget` |
| Monotonicity | within a position, price is non-increasing in points, at every `w_floor` |
| Ramp headroom | `ramp_span / (replacement - last_rostered)`; must be `>= 1` per position |
| Unreachable positions | absent entirely, same as `01`/`02` |
