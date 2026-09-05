# 01 · The roster template (FAQ)

### What does this compute?

Nothing computed — it's the frozen shape of one team's roster: how many
starting slots at each position, how many flex slots and what each accepts,
how many bench spots, and the league-wide constants (teams, budget, min bid)
every other model reads from one place.

### Why not just hardcode the fantasy-standard roster shape?

Because there isn't one. Flex types vary (`FLEX`, `REC_FLEX`, `SUPER_FLEX`
each accept a different position set), and which positions a league plays at
all isn't fixed either — this league's Sleeper settings never mention K, so
kickers aren't part of its template anywhere. Reading this league's actual
settings once, into one object, is what keeps every downstream model from
carrying its own copy of these numbers.

### How does it actually work?

`LeagueConfig` is a frozen dataclass holding the raw settings, plus three
derived methods. `draftable_positions()` unions the positions with a
concrete starting slot and the positions any flex slot accepts. `flex_peers(position)`
returns every other position that could take a flex slot away from it —
the union across flex types, since a position competes with everyone it
could ever lose a slot to, not just at one specific flex. `roster_size` sums
concrete, flex, and bench slots into one team's total.

### What's the output, precisely?

An immutable template: `LEAGUE_CONFIG`, the one instance every seat in
`03-seats-and-sales.md` is built from, plus the three derived queries above.

### What does that look like in practice?

- **This league's template:** `starting_slots={QB:1, RB:2, WR:2, TE:1, K:0,
  DEF:1}`, one each of `FLEX`/`REC_FLEX`/`SUPER_FLEX`, 6 bench — `roster_size`
  = 16.
- **Flex peers:** `SUPER_FLEX` accepts QB/RB/WR/TE, so `flex_peers("QB")` is
  `["RB", "WR", "TE"]` — QB competes with all three for that one slot. `flex_peers("DEF")`
  is `[]` — no flex slot anywhere accepts DEF, so it has no peer-derived floor.
- **Worked example:** `draftable_positions()` on this league's settings
  returns `["QB", "RB", "WR", "TE", "DEF"]` — K has no starting slot and
  isn't in any flex's eligible list, so it's excluded even though it's a
  real NFL position.

### What about `plays_positions`?

An optional override field, currently unused by anything that constructs a
`LeagueConfig`. It exists to answer "what does this league play" without
deriving it from slot counts, for a scenario where a residual config might
zero out a position's counts once its slots are all spoken for. `03-seats-and-sales.md`'s
real-slot model never zeros counts — the template stays fixed and only the
*open* set shrinks — so nothing that exists today needs this field to be set.

### What's the catch?

The template can't tell you what's actually happened in a draft — it has no
concept of a sale, a seat, or money spent. Every question about roster state
mid-draft is answered by `03-seats-and-sales.md`, which is built once from
this template and then diverges from it one sale at a time.

---

## Reference

**Depends on:** nothing upstream — this is read from Sleeper's draft
settings once, at league creation. **Implemented in:**
`python/vorp/league/config.py` (`LeagueConfig`, `LEAGUE_CONFIG`).
**Done when:** `draftable_positions()`, `flex_peers()`, and `roster_size`
match this league's actual Sleeper settings for every position.

| Input | Description |
| --- | --- |
| Sleeper draft settings | `teams`, `budget`, starting/flex/bench slot counts |
| `FLEX_ELIGIBILITY` | which positions each flex type accepts, hardcoded per league rules |
| `STREAMING_POSITIONS` | positions excluded from bench eligibility (`last_rostered.py`'s rule) |

| Output | Description |
| --- | --- |
| `LEAGUE_CONFIG` | the one template instance every model and every seat reads |
| `draftable_positions()` | positions this league's template plays anywhere |
| `flex_peers(position)` | positions that can take a flex slot away from `position` |
| `roster_size` | total slots (concrete + flex + bench) on one team |
