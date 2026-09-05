# 02 · The Boberto twin (FAQ)

### What does this compute?

`scripts/export-boberto.ts` produces `data/boberto-{season}.csv` — a
second-opinion projection feed. It pulls FantasyPros projections and market AAV
(ESPN, NFFC, Yahoo) from `boberto.app`, recomputes each player's half-PPR points
from the raw stat line, and matches every row back to a Sleeper `player_id` so it
joins cleanly onto `01-projections-export.md`'s table.

### Why a second feed — isn't `projections-{season}.csv` enough?

The two things Sleeper doesn't give you are an independent opinion and a real
auction market. This feed supplies both: a non-Sleeper projection to sanity-check
against, and observed average auction values from three platforms. It also
carries the *raw stat line* per player, so points are recomputed under this
repo's exact half-PPR rules rather than trusting a black-box season total.

### How are half-PPR points computed?

`halfPprPoints` scores the projected stat line directly:

```
pass_yds/25 + pass_tds*4 − pass_ints*2
+ rush_yds/10 + rush_tds*6
+ rec_yds/10  + rec_tds*6 + receptions*0.5
− fumbles_lost*2
+ fg_0_39*3 + pat_made                        (kickers)
+ def_sacks + def_ints*2 + def_fumble_recoveries*2 + def_tds*6 + def_safeties*2
```

Any absent stat key is treated as `0`. Recomputing Josh Allen's 2026 line —
`3816.77` pass yds, `27.42` pass TDs, `11.19` INTs, `585.97` rush yds, `11.82`
rush TDs, `4.1` fumbles — gives `152.67 + 109.68 − 22.38 + 58.60 + 70.92 − 8.20 =
361.29`, exactly the `season_pts_half_ppr` the CSV emits for him.

### Why does every row need a Sleeper `player_id`, and why is that hard?

The `player_id` is the join key — it's how this feed lines up against the
projections table and everything the VORP engine builds on. Matching is hard
because the feed and Sleeper disagree in four ways: nicknames ("Hollywood Brown"
vs the legal "Marquise Brown"), team abbreviations (`ARZ`/`JAC`/`LA` vs
`ARI`/`JAX`/`LAR`), position (Sleeper lists Kyle Juszczyk as `FB`, the feed as
`RB`), and defense naming ("Texans D/ST" vs "Rams" vs "New York Jets").

### How does matching actually work?

`normalizeName` lowercases, strips `.` and `'`, turns hyphens into spaces, drops
anything non-alphabetic, and removes the suffix tokens `jr/sr/ii/iii/iv/v`; then
`NAME_ALIASES` maps a normalized nickname onto the normalized legal name.
`buildPlayerIndex` builds three lookups — `byNamePosition`, `byName`, and
`defenseByTeam` (keyed by team abbreviation, since a Sleeper DEF's `player_id`
*is* the abbreviation). `matchSleeperPlayer` then:

```
if position == DEF:  return defenseByTeam.get(normalizeTeam(team))     # any DEF naming
name = normalizeName(feed.name)
return resolve(byNamePosition[name|position], team)                    # exact name+position
    ?? resolve(byName[name], team)                                     # fallback: name alone
```

`resolve` narrows a name bucket: one candidate wins outright; several are filtered
to same-`team`, then to `active !== false`; still ambiguous returns `null`.
`normalizeTeam` runs feed abbreviations through `TEAM_ALIASES`
(`ARZ→ARI, JAC→JAX, LA→LAR, FA→null`) first.

### Why exact aliases instead of a fuzzy matcher?

Because a fuzzy matcher trades a few known misses for silent wrong matches, and a
wrong `player_id` is worse than a blank one — it quietly misprices a real player.
Aliases are applied *inside* `normalizeName`, so they run over the Sleeper side of
the index too; an alias can therefore only ever merge two spellings of a player
who exists, never invent a match to a player who doesn't.

### What's the output, precisely?

A CSV keyed by `player_id`, `player`, `position`, `team`, `bye_week`,
`season_pts_half_ppr`, the three `aav_*` columns, and the raw `STAT_COLUMNS`. A
projection row that fails to match is still emitted — with a blank `player_id`
and the feed's own name/position/team — and printed to the console for curation.
An *AAV* row that fails to match is dropped, since it has no points row to attach
to; the run reports how many.

### What does that look like in practice?

- **Defense, any spelling:** "Jets", "Jets D/ST" and "New York Jets" all resolve
  to `player_id` `NYJ` via `defenseByTeam` — name text is ignored for DEF.
- **Feed team abbreviation:** a "Jaguars D/ST" row tagged team `JAC` normalizes
  to `JAX` and matches `player_id` `JAX`.
- **Position disagreement:** Kyle Juszczyk comes in as `RB`; the `name|RB` bucket
  is empty, so the name-only fallback finds him at `player_id` 3 despite Sleeper's
  `FB`.
- **Worked example:** a feed row `{ name: "Hollywood Brown", position: "WR", team:
  "PHI" }` — `normalizeName` produces `hollywood brown`, `NAME_ALIASES` rewrites
  it to `marquise brown`, and the `marquise brown|WR` bucket resolves to
  **`player_id` 6**, Sleeper's Marquise Brown.

### What about two players who share a name?

`resolve` breaks the tie on team, then on active status; it does not guess. Two
Mike Williamses (`player_id` 4 at `LAC`, 5 at `NYJ`) resolve correctly because a
feed row tagged `NYJ` filters to the one `NYJ` candidate → `player_id` 5. If team
can't narrow it to one and active status can't either, it returns `null`. The
wrong answer is picking the first or most-recently-seen candidate — that would
attach real points to the wrong man.

### What's the catch?

Kicker and defense points are approximate. The feed carries no field-goal
distance buckets and no points-allowed, so `halfPprPoints` scores K off a single
`fg_0_39` bucket and DEF off sacks/turnovers/TDs only (the `ponytail` note in the
code). It's deliberately left rough — upgrade the scoring only if K/DEF pricing
ever starts to matter.

### How do I fix a name that doesn't match?

Run `npm run export:boberto 2026`; it prints every unmatched projection under
"add a `NAME_ALIASES` entry…". Add one line per genuine miss to `NAME_ALIASES`
in `src/boberto.ts`, both sides in normalized form, and re-run. Keep it exact —
curating misses by hand is the deliberate alternative to a fuzzy matcher.

---

## Reference

**Depends on:** the Sleeper player dump via `src/sleeper.ts` (`fetchPlayers`,
`sleeperPlayerFullName`) and the `boberto.app` FantasyPros projections + market
AAV endpoints (`fetchBobertoProjections`, `fetchBobertoAav`). **Implemented in:**
`scripts/export-boberto.ts` (`halfPprPoints`, `STAT_COLUMNS`, `AAV_SOURCES`,
`main`) over the matching machinery in `src/boberto.ts` (`normalizeName`,
`NAME_ALIASES`, `buildPlayerIndex`, `matchSleeperPlayer`, `resolve`,
`normalizeTeam`, `TEAM_ALIASES`). **Done when:** `npm test` passes
`src/boberto.test.ts` — "Hollywood Brown" resolves to `player_id` 6, a `NYJ`
Mike Williams to 5, an `RB`-tagged Juszczyk to 3, and "Jets"/"Jets D/ST"/"New
York Jets" all to `NYJ` — and `npm run export:boberto 2026` writes
`data/boberto-{season}.csv`.

| Input | Description |
| --- | --- |
| `GET /players/nfl` (Sleeper) | the index every feed row is matched against |
| `boberto.app /fantasypros/projections?season=` | per-player raw stat lines and identity |
| `boberto.app /market/aav?season=&source=all` | AAV per source (`espn`, `nffc`, `yahoo`) |

| Output | Description |
| --- | --- |
| `data/boberto-{season}.csv` | one row per feed projection; keyed to a Sleeper `player_id` when matched |
| `season_pts_half_ppr` | half-PPR points recomputed from the stat line by `halfPprPoints` |
| `aav_espn` / `aav_nffc` / `aav_yahoo` | observed market auction value, blank if that source lacked the player |
| `STAT_COLUMNS` | the raw projected stat line, in fixed emit order |
| unmatched rows | emitted with a blank `player_id` and listed on the console for `NAME_ALIASES` curation |
