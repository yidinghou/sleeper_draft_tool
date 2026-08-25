# 02 · Value over last rostered (FAQ)

### What does this compute?

Value over last rostered: the score of the very last player who'll
actually get *drafted at all* — starting or bench — at each position.
It pools every roster spot, not just starting slots.

### Why not just reuse replacement level for this?

Replacement level (`01`) only pools starting slots (concrete + flex),
`teams × 10` here — it answers "what does a freely-available *starter*
score." It says nothing about bench depth, so it can't answer
"will anyone actually spend a dollar on this player at all."

### So how does it actually work?

Same league-wide optimal fill as `01` (`solveOptimalFill`), just over a
bigger pool: every roster spot, starting and bench, `teams × 16 = 192`
here. Bench slots differ from FLEX/REC_FLEX/SUPER_FLEX in one way — they
don't match one fixed eligibility list, they accept anybody at a
position the league's template plays *somewhere*
(`LeagueConfig.draftable_positions()`). Two real-data corrections sit on
top of that: bench eligibility is restricted to draftable positions
specifically because an earlier version let bench slots accept *any*
position, including K — which this league's template never plays at
all, starting or bench — and put a nonzero level on kickers that never
belongs there. Separately, `DEF` is pulled out of bench eligibility
entirely via `STREAMING_POSITIONS`, even though it's fully draftable at
its own concrete slot: real managers stream defense off waivers rather
than draft bench depth for it, no matter how a backup defense projects.

### What's the output, precisely?

For each position, the best player **not** in the full-roster selected
set — same definition as `01`'s replacement level, just measured
against the bigger starting+bench pool.

### What does that look like in practice?

- **Real bench depth (RB):** several running backs outscore the
  alternatives available for bench slots → more RBs get selected in the
  full-roster fill than the starting-only fill → last-rostered level for
  RB comes in lower than replacement level for RB.
- **No concrete slot, still reachable (WR):** a league where WR has no
  concrete slot but is FLEX-eligible can still roster a WR off the
  bench, as long as he outscores the bench-slot competition.
- **Streamed position (DEF):** even a backup defense projected to
  outscore everyone else on the board never claims a bench slot — DEF's
  `selected_count` is pinned to exactly `teams`, one per team, so its
  last-rostered level always equals its replacement level exactly.
- **Worked example:** 12 teams, `teams × 10 = 120` starting slots vs.
  `teams × 16 = 192` total roster spots → 72 extra bench slots the
  full-roster fill has to work with that the starting-only fill doesn't.

### Why is a superflex position's level floored at its flex peers?

Because pooling a position against itself alone ignores who it actually
competes with for a slot. QB has one concrete slot and a deep pool, so the
fill put QB's last-rostered level at 50.9 while RB, WR and TE all sat above
77 — but SUPER_FLEX takes all four, and nobody rosters the 50th quarterback
when a better running back is free for the same slot. Each flex-eligible
position is therefore floored at the minimum raw level among its flex peers,
which lifts QB to 77.2 and leaves every other position untouched, since QB
was the group minimum. A position in no flex slot anywhere (DEF here) has no
peers and keeps exactly the level the fill solved.

### What about a position absent from the template entirely, like K?

Unreachable — no bid, not zero — exactly as it is for replacement level
in `01`. Bench only adds *depth* to a position already in the template;
it never adds a position the template doesn't play anywhere. Reachability
for last-rostered always agrees with reachability for replacement level,
position by position.

### What's the catch?

DEF's exclusion from bench eligibility is a hand-set calibration, not
something derived from the board — same kind of judgment call `01`
makes by choosing optimal points-maximization over a measured split.
The metric is only as good as `STREAMING_POSITIONS`; add a position to
that list for the wrong reason and its last-rostered level silently
collapses to its replacement level.

### Does this reflect a specific team's actual bench mid-draft?

No. Like `01`, this solves the abstract "teams × slots, nobody's roster
decided yet" case pooled league-wide — not one seat's actual bench,
which depends on the sales record and is out of scope until the
dynamic/live layer exists.

---

## Reference

**Depends on:** `01-calculating-replacement.md`'s league-wide optimal fill.
**Implemented in:** `python/vorp/last_rostered.py` (`_flex_peer_floor` for the
superflex correction). **Done when:** for a
hand-written fixture, the league-wide optimal fill pooled over every
roster spot (starting + bench) selects a lower-value player at a position
with real bench depth than the starting-only fill does, and a position
absent from the league's template entirely is unreachable exactly as it
is for replacement level — bench included.

| Input | Description |
| --- | --- |
| Slots | `teams × (concrete + flex + bench slots)`, from league config |
| Bench eligibility | `LeagueConfig.draftable_positions()` — any position with a concrete slot or flex eligibility somewhere in the template; not literally every `Position` |
| Players, objective | same as `01`: every board player, maximize total points |
| Flex peers | `LeagueConfig.flex_peers()` — positions sharing a flex slot; a position's level floors at the minimum raw level among them |

| Output | Description |
| --- | --- |
| Selected set | every player chosen into a starting **or bench** slot, league-wide |
| Last-rostered level, per position | the best player at that position **not** in the selected set |
| Reachable | identical to replacement level's `reachable` for the same position — bench changes depth, never reachability |
