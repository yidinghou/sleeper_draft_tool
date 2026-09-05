# 03 · VORP-implied and VOLR-implied value (FAQ)

### What does this compute?

Two independent dollar figures for every draftable player, on the same
scale, and **deliberately no single bid**:

1. **VORP $** — what he's worth if the whole budget were apportioned by
   VORP alone, among everyone who clears replacement level.
2. **VOLR $** — what he's worth if the whole budget were apportioned by
   value over last rostered alone, among everyone who clears the
   last-rostered bar.

Each independently sums to `teams × budget`. Neither is "the price."
The human reads both and decides.

### Why is there no single bid?

Because any single number has to pick a baseline on the reader's behalf,
and the two baselines disagree *most* exactly where the decision is
hardest — at the starter/bench boundary.

An earlier version did collapse them: starters priced off the starter
pool by VORP, bench-only picks off the bench pool by VOLR, 90/10. It
produced this, at QB, in the real 2026 board:

```
24  Bryce Young    224.6 pts   STARTER   $5     <- priced vs replacement (214.8)
25  Cam Ward       214.8 pts   bench     $10    <- priced vs last-rostered (50.9)
```

**A worse player, priced at twice as much.** Young barely clears a high
bar, so his VORP margin is tiny; Ward towers over a low bar, so his VOLR
margin is huge. Nothing forces the two curves to meet at the seam, so
the combined "bid" was non-monotonic in points — the one property a
price list must have.

Splitting the two lenses back apart fixes it by construction: within a
position each lens measures every player against *one* bar, so each is
monotonic in points. There were 0 monotonicity violations across all
positions and both lenses on the 2026 board after the split.

### Why does each lens spend the whole budget, rather than 90/10?

So the two numbers are **comparable**. Sizing VORP $ at 90% and VOLR $
at 10% puts them on different scales — roughly $18 against $3 for the
same player — and a reader can't weigh two numbers that don't share a
unit. Giving each lens the full budget means "$26 under VOLR thinking"
and "$16 under VORP thinking" are the same kind of statement.

The 90/10 `starter_budget_pct` split only ever existed to size the two
halves of a single blended bid. With no blended bid, it has nothing to
size — so `split_budget` and `calculate_bids` are **gone**, not parked in
the library against a future that may never call them. `04` combines the
two lenses by blending the *bars*, which needs no budget split at all; if
a live-draft layer ever wants one, it can be written then, against what
that layer actually needs.

### How should a human read the two together?

Read **the gap**, not either number alone.

- **VORP $ ≫ VOLR $** — value concentrated in being startable. He clears
  a high bar but the position has depth behind him, so missing out is
  survivable.
- **VOLR $ ≫ VORP $** — value that holds up against the waiver wire.
  He's barely a starter, but the drop to freely-available is a cliff.
- **Both high** — genuinely scarce; the drop-off is steep at both bars.

Cam Ward and Daniel Jones sit at VOLR $22 with no VORP $ at all: not
startable in a 24-QB superflex field, but far above what's actually free
at QB. Whether that's worth $22 to *you* depends on how you value a QB2,
which is precisely the judgement this module refuses to make for you.

### Why not just split the whole budget proportional to VORP?

VORP is only defined for starters — it says nothing about bench-only
picks, so it can't price the whole selected set on its own. That's why
VOLR $ exists alongside it rather than instead of it: VOLR's population
(`02`'s selected set) is a superset of VORP's (`01`'s), so every drafted
player has at least one figure, and starters have both.

Separately, a pure proportional split hands $0 to anyone at exactly zero
margin over baseline, and $0 isn't a real bid in an auction with a $1
floor — hence the floor below.

### How does each lens actually work?

Identical machinery, different bar and different population. Reserve
`min_bid` for each of that lens's members out of `teams × budget`,
apportion the remainder proportional to margin
(largest-remainder/Hamilton, so it sums exactly), then add the floor
back.

| | Bar | Population |
| --- | --- | --- |
| **VORP $** | `replacement_level` (`01`) | `01`'s selected set — starters |
| **VOLR $** | `last_rostered_level` (`02`) | `02`'s selected set — everyone drafted |

A player outside a lens's population gets `null` for that lens, never
`$0` — Cam Ward has no VORP $ because he isn't a starter, which is
information, not a price of zero.

### What if a position's pool runs out?

Then there's no "best player who didn't make it" to read the bar off,
and the level comes back `None` rather than silently collapsing to
`0.0`. Callers substitute the worst player in that pool as a
floor-bound stand-in (`_effective_bar`) and the output flags it via
`pool_exhausted`. This is a data-coverage gap — the source projections
listing fewer players at a position than the league has slots for — not
a real bar of zero. It shows up at QB in the weeks-1-3 window, where
Sleeper only publishes weekly projections for players expected to play.

### Doesn't the $1 floor distort a lens?

Only when the floors eat most of the pool. Each lens reports
`floor_pressure` — the share of its pool consumed by `min_bid` floors.
On the 2026 board both are small (VORP 0.05, VOLR 0.08) because each
lens has the whole budget to work with. When `floor_pressure` approaches
1.0 the lens is mostly floor and its ordering barely reflects margin;
surface it rather than letting the column look like a valuation.

### What's the output, precisely?

Per player: `vorp_dollar` (whole dollars `>= min_bid`, or `null` if he
doesn't clear replacement level) and `volr_dollar` (same, or `null` if
he doesn't clear the last-rostered bar). A player outside a lens's
population is `null` there, never `$0`. A position the template never
plays at all (K here) is absent from both — unreachable, not $0.

### What does that look like in practice?

- **Two starters, one with double the VORP:** the higher-VORP starter's
  share of the VORP lens is exactly double the other's.
- **Two players, one with double the last-rostered margin:** same rule,
  against the VOLR lens and the last-rostered baseline instead.
- **Worked example:** 12 teams, $200 budget, $1 floor → each lens
  apportions `12 × 200 = 2400`. The VORP lens has 120 members, so it
  reserves `120 × $1 = $120` and apportions `$2280` by VORP margin. The
  VOLR lens has 192 members, so it reserves `192 × $1 = $192` and
  apportions `$2208` by VOLR margin. Each column independently sums to
  exactly `2400`.
- **Reading the pair:** Sam Darnold comes out VORP $16 / VOLR $26 —
  startable, but the QB drop-off past him is steeper than his margin
  over replacement suggests. Cam Ward comes out VORP `null` / VOLR $22 —
  not startable at all, yet still far above freely-available QB.

### What about a player sitting at exactly zero margin?

He still gets `min_bid`, not $0, in whichever lens he's a member of.
This applies to the starter whose points exactly equal replacement level
(VORP = 0) and to the player whose points exactly equal the
last-rostered level (VOLR = 0).

### What about a streaming position, like DEF?

`02` pins DEF's `last_rostered_level` to equal its `replacement_level`
exactly and keeps it out of the bench-only set, so a defense's two
figures coincide by construction — no bench-side depth margin exists for
it to draw on.

### What's the catch?

The two lenses are each internally monotonic, but they are **not
directly rankable against each other across the whole board**. VOLR $
has a larger population and a lower bar, so it compresses the top and
lifts the middle relative to VORP $. Sorting the board by VOLR $ is a
legitimate view; treating "VOLR $ > VORP $" as *proof* a player is
underpriced is not — it partly just reflects the two bars.

The deeper catch is the one this module now refuses to paper over:
neither lens is the price. Turning the pair into a number you actually
bid is a judgement about your roster, your budget left, and how much you
value a QB2 — and that judgement is yours, not the model's.

### Does this reflect a team's actual remaining budget mid-draft?

No. Like `01` and `02`, this solves the abstract pre-draft case against
the full board — not a specific seat's actual remaining budget mid-draft,
which depends on the sales record and is out of scope until the
dynamic/live layer exists.

---

## Reference

**Depends on:** `01-calculating-replacement.md`'s replacement level and
selected set, `02-value-over-last-rostered.md`'s last-rostered level and
selected set, league config (`python/vorp/league_config.py`).
**Implemented in:** `python/scripts/bid_value.py` — both lenses via
`apportion_with_floor` from `python/vorp/bid_value.py`, which is now just
the shared apportionment (`apportion`, `apportion_with_floor`,
`floor_pressure`, `_effective_bar`) and holds no budget split of its own.
**Done when:** for a hand-written fixture board, every player in a
lens's population gets a figure `>= min_bid`, each lens independently
sums to exactly `teams × budget`, a player outside a lens is `null`
there rather than `$0`, and — the property the collapsed bid failed —
**each lens is monotonic in points within a position**: no player
out-prices someone who scores more than he does at the same position.

| Input | Description |
| --- | --- |
| Starting selected set | from `01`: which players fill starting slots, league-wide |
| Full-roster selected set | from `02`: everyone drafted, starting or bench |
| VORP, per starter | `points − replacement_level[position]`, from `01` |
| Value over last rostered | `points − last_rostered_level[position]`, from `02` |
| League config | `teams`, `budget`, `min_bid`, from `LeagueConfig` |

| Output | Description |
| --- | --- |
| VORP $ | `teams × budget` split by VORP among `01`'s selected set; `null` outside it |
| VOLR $ | `teams × budget` split by VOLR among `02`'s selected set; `null` outside it |
| `floor_pressure`, per lens | share of that lens's pool consumed by `min_bid` floors; near 1.0 means the lens is mostly floor |
| Reconciliation | **each lens independently** sums to `teams × budget` |
| Monotonicity | within a position, each lens is non-increasing in points |
| Unreachable players | absent from both — same reachability as `01`/`02` |
| *(no bid)* | deliberately not produced; see "Why is there no single bid?" |
