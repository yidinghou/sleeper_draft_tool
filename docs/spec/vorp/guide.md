# The VORP engine — reproduction guide

How to rebuild the valuation engine from scratch, in dependency order. Every
layer sits on the [league model](../league/index.md) substrate — the roster
template, the slot-assignment matching, and the seats that hold real slots and
money — and on the board of projected points, `data/projections-2026.csv`, which
the [data pipeline](../data/index.md) exports. Build the league module first
(see its own [guide](../league/guide.md)); then build these in order and each
layer's tests already have their dependencies in place.

## The substrate everything shares

Two inputs feed every step below, so stand them up before step 1:

- **The league model** (`python/vorp/league/`) — `LeagueConfig` /
  `LEAGUE_CONFIG` (the frozen template), `solve_optimal_fill` /
  `summarize_by_position` / `assign_to_slots` (the matching engine), and
  `LeagueState` / `Seat` / `max_bid` (seats holding real slots, so a single sale
  is expressible). Steps 1, 2, 7, 8, 9 all call into it; step 9b (below)
  would too, once built.
- **The projections board** — `data/projections-2026.csv`, loaded by
  `vorp.csv_loader` into `RosterFillPlayer(player_id, position, points)`. It is a
  **living file**: the data pipeline refreshes it, so tests that touch real data
  assert invariants (never hard-coded dollars) or freeze a snapshot fixture.

## Rebuild order

| Spec | Implemented in | Depends on |
| --- | --- | --- |
| [01 · Replacement level](01-calculating-replacement.md) | `python/vorp/replacement_level.py` | league config + `roster_fill` matching |
| [02 · Value over last rostered](02-value-over-last-rostered.md) | `python/vorp/last_rostered.py` | `01`'s fill, over the full-roster slot pool |
| [03 · VORP $ / VOLR $](03-vorp-to-bid.md) | `python/vorp/bid_value.py` (lenses assembled in `python/scripts/auction/bid_value.py`) | `01` + `02` levels and selected sets |
| [04 · Blended-bar pricing](04-blended-bar-pricing.md) | `python/vorp/models.py` (`progressive_blend`); exported by `python/scripts/auction/blended_price.py` | `01` + `02` bars, `03`'s apportionment |
| [05 · Principles](05-principles.md) | `python/vorp/principles.py`; report in `python/scripts/auction/principles.py` | `04`'s model registry + all bars |
| [07 · Live draft board](07-live-draft-board.md) | `python/vorp/board.py` (`price_board`) — pricing core only, no server | `04` re-solved over a residual `LeagueState` |
| [08 · Seat value](08-seat-value.md) | `python/vorp/seat_value.py` | league matching + `04`'s board price and exchange rate |
| [09 · Best affordable roster](09-optimal-roster.md) | `python/vorp/optimal_roster.py` (`plan_roster`); printed by `python/scripts/auction/optimal_roster.py` | `08`'s lineup value + `04`/`07` prices |
| [09b · Roster scenarios](09b-roster-scenarios.md) | **WIP** — would be `python/scripts/auction/roster_scenarios.py` | `09`'s `plan_roster` + `07`'s `price_board`, N seeded times |

(There is no spec `06`; the numbering skips it.)

## Step 1 — `python/vorp/replacement_level.py`

The league-wide optimal fill over **starting** slots (concrete + flex), and the
bar it leaves behind at each position. `calculate_replacement_levels` pools
every seat's starting slots via `LeagueState.opening(config).starting_slots()`,
runs `solve_optimal_fill`, and reads replacement level as the best player left
outside the selected set. Reachability, `selected_count`, and `pool_exhausted`
come straight from `summarize_by_position`.

## Step 2 — `python/vorp/last_rostered.py`

The same fill over **every** roster spot — starting *and* bench
(`full_roster_slots()`) — so the bar is the last player drafted at all, not just
the last starter. Two corrections live here: bench eligibility is restricted to
`draftable_positions()` (a position the template never plays, like K, stays out
entirely), and `_flex_peer_floor` lifts each flex-eligible position's level to
the worst level among its flex peers (so a superflex league doesn't claim the
50th QB is the last rostered one). `STREAMING_POSITIONS` pins DEF to one per team.

## Step 3 — `python/vorp/bid_value.py`

The shared whole-dollar apportionment, nothing more: `apportion` (largest-
remainder/Hamilton, sums exactly to the pool), `apportion_with_floor` (reserve
`min_bid` per member, split the rest, add the floor back), `floor_pressure`, and
`_effective_bar` (fall back to the worst player in an exhausted pool rather than
a bar of zero). The two lenses of `03` — VORP $ against `01`'s bar and
population, VOLR $ against `02`'s — are assembled from these in
`python/scripts/auction/bid_value.py`; each independently spends the whole
`teams × budget`, and there is deliberately no single combined bid.

## Step 4 — `python/vorp/models.py`

Every candidate valuation model behind one `(players, config) -> Valuation`
interface, so `05` can grade them. The shipped model is `progressive_blend`:
each position gets a bar that slides linearly **in points** between its
replacement level (top) and last-rostered level (bottom), with the top
`FULL_WEIGHT_SHARE = 0.75` of starters never blended; the resulting margins are
apportioned with `apportion_with_floor`. `w_floor` is the one dial (ships at
`0.5` via `DEFAULT_W_FLOOR`). The `REGISTRY` also holds strawmen
(`points_proportional`, `fixed_flex`, `starters_only`) that exist to be failed.

## Step 5 — `python/vorp/principles.py`

The pass/fail matrix that turns "which model is better" into a table. See the
[principles harness](#what-the-principles-harness-guarantees) below for what it
guarantees. Report rendering is `python/scripts/auction/principles.py`.

## Step 7 — `python/vorp/board.py`

Re-solves `04`'s pricing against the league that is actually left: the sold set
read off a residual `LeagueState`, the money pool and open slots shrinking per
sale, `blend_weights` solved once then re-apportioned at three floor weights
(`w_floor`, `1.0`, `0.0`) for price / VORP $ / VOLR $. `price_board` is the
pricing core only — it was lifted out of `scripts/draft_demo.py`'s repricing
logic, which now imports it instead of keeping its own copy. See
[`07 · Live draft board`](07-live-draft-board.md) for the full spec. The
live-server module that would put an HTTP surface around it,
[`../board/index.md`](../board/index.md), doesn't exist yet.

## Step 8 — `python/vorp/seat_value.py`

The board price corrected by one seat's own roster, then capped by its own
budget. `seat_vorp` is the points a player adds to that seat's optimal starting
lineup, with a freely-available replacement body imputed into every open slot
(`free_agents`) so the matching maximizes points, not head-count. `seat_bid`
clamps to `max_bid`. An empty seat's values equal league VORP exactly, so this
is a refinement of `04`, not a rival.

## Step 9 — `python/vorp/optimal_roster.py`

The auction's knapsack: `plan_roster` greedily buys the affordable player
with the best marginal-points-per-dollar (`08`'s value re-solved as the set
grows), stopping when no affordable player adds a startable point, with
`exclude_positions` and `fill_all` as the two knobs on top. Printed by
`python/scripts/auction/optimal_roster.py`. See
[`09 · The best affordable roster`](09-optimal-roster.md).

## Step 9b — `python/scripts/auction/roster_scenarios.py` (not yet built)

Planned as a pure-Python wrapper (no dedicated module, no new model): price the
board once with `07`, then for each integer seed jitter every price by a
uniform `±sigma` and re-run `09`, laying the columns out side by side and
flagging the buys present in every seed. See
[`09b · Roster scenarios`](09b-roster-scenarios.md). Both `09` and `07` are
now built; only the wrapper script itself is left.

## Testing

Run, from the repo root:

```
python -m pytest python/tests/test_replacement_level.py python/tests/test_last_rostered.py \
    python/tests/test_bid_value.py python/tests/test_principles.py \
    python/tests/test_seat_value.py python/tests/test_board.py \
    python/tests/test_optimal_roster.py
```

(Equivalently, from `python/`, drop the `python/` prefix — `pyproject.toml` sets
`pythonpath = ["."]` so the `vorp` package imports without an install. Or just
`python -m pytest python/tests/` to run everything currently checked in.) These
seven suites are what's implemented today, all passing.

What each suite pins:

- **`test_replacement_level.py`** — flex contention (a strong TE class
  claims a shared flex slot from a weaker RB, and vice versa), replacement level
  as "the best player left outside the selected set" (the 13th TE behind 12
  concrete slots), and `reachable=False` / `level=None` for a position with no
  slot at all (K).
- **`test_last_rostered.py`** — a bench-eligible position with no concrete
  slot is still rosterable, real bench depth pushes the level below replacement,
  DEF is streamed (exactly one per team, never benched), the superflex flex-peer
  floor lifts QB, and reachability agrees with `01` position for position.
- **`test_bid_value.py`** — each lens splits its pool in proportion to
  margin, a zero-margin member still gets `min_bid`, each lens independently
  reconciles to `teams × budget`, and — the property the collapsed bid failed —
  each lens is monotonic in points within a position.
- **`test_principles.py`** — the strawman fails `baseline-not-points`,
  `progressive_blend` passes every law at every `w_floor`, and the seam
  regression (`test_blending_prices_inverts_where_blending_bars_does_not`) keeps
  price-blending's inversion reproducible now that the two-lens dial is gone.
- **`test_seat_value.py`** — a player who reaches no startable slot is
  worth 0, an empty seat values at exactly league VORP, the lineup leaves open
  whichever slot a free body fills best, and the `max_bid` clamp exactly (opening
  seat caps at `185`, a broke-but-not-full seat is "out" at `0`).
- **`test_board.py`** — with nothing sold `price_board` reproduces
  `progressive_blend`'s prices exactly at the same `w_floor`, and one sale
  removes exactly the sold player from the rows and exactly one slot from the
  residual state, with the priced rows still reconciling to the residual pool.

- **`test_optimal_roster.py`** — no plan outspends its seat's budget,
  `spend + reserve <= budget`, `len(targets) <= open slots`, a plan never
  lowers the lineup (`points_after >= points_before`), `exclude_positions`
  and `fill_all` behave as documented, and greedy matches the brute-forced
  optimum on a flat-price board small enough to enumerate.

`09b` is expected to stay a thin script pinned by `09`'s determinism test
rather than getting its own suite, per its spec — it doesn't exist yet.

## What the principles harness guarantees

`python/vorp/principles.py` (spec [05](05-principles.md)) runs every registered
model against **ten laws** and three calibrations, and the shipped model passes
all ten laws. A law is pass/fail and must hold or the output isn't a price list;
a calibration is a measured-not-enforced claim about matching the market. The
ten laws:

`reconciles` (prices sum to exactly `teams × budget`), `monotonic` (no player
out-prices a higher scorer at his position), `floor` (every price `>= min_bid`),
`fills-rosters` (exactly as many players priced as the league drafts),
`no-phantom-positions` (a position the template never plays is absent, not
priced), `no-streamed-depth` (a streamed position gets one per team),
`informative-ordering` (prices mostly above the floor, or the bench is ranked),
`baseline-not-points` (adding a constant to every projection changes no price —
value is margin, not production), `ramp-slope` (a sliding bar slides slower than
points do, checked structurally so no board can produce a crossing), and
`mid-draft` (every position with players and slots left is still priceable after
a quarter and past a position's starting slots being consumed).

The three calibrations — `market-mae`, `bench-spend`, `top-price` — are reported
with arbitrary thresholds, never enforced; disagreeing with the market is often
the point.

## Gotchas

- **`w_floor` is the one dial, and it is calibration, not derivation.** It sets
  how far the bar slides toward the last-rostered level; `1.0` is pure VORP,
  ships at `0.5`. `FULL_WEIGHT_SHARE = 0.75` (where the ramp *starts*) is a fixed
  part of the model's shape in `models.py`, deliberately *not* a second dial —
  two dials that both move prices the same way give two ways to say the same
  thing. Neither number was measured from anything; they land the starter/bench
  split and market error near their best on the 2026 board, and a different board
  could put them elsewhere.
- **VORP is floored at 0.** `max(0, points − bar)` everywhere: nobody is worth
  less than a freely-available replacement, so a below-bar player has a margin of
  0, not a negative one. This is what lets `03`'s apportionment and `08`'s seat
  value stay non-negative, and it is why a player at exactly the bar still gets
  `min_bid` rather than `$0`.
- **`09`'s knapsack is greedy, not exact.** The exact auction knapsack is
  NP-hard; `plan_roster` approximates it by marginal-points-per-dollar,
  exactly optimal only when prices are flat — pinned by
  `test_greedy_equals_the_brute_forced_optimum_on_a_flat_price_board`. See
  [`09 · The best affordable roster`](09-optimal-roster.md) for the full
  argument.
- **Unreachable is not `$0`, and `pool_exhausted` is not a bar of 0.** A position
  with no slot anywhere (K) is absent from every output; a position whose pool
  ran short comes back with `level=None` and callers substitute the worst player
  in the pool (`_effective_bar`), never zero. Reading either as a real bar of
  zero inflates the whole position.
- **The real data files are living.** `data/projections-2026.csv` refreshes, so
  anything reproducible either asserts invariants or freezes a snapshot fixture.
  Generated JSON outputs under `data/` are gitignored build outputs, not
  checked-in fixtures.
