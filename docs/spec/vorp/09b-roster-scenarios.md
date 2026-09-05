# 09b · Roster scenarios (FAQ) — WIP

> **Work in progress — not yet implemented.** `python/scripts/roster_scenarios.py`
> doesn't exist yet. It wraps [`09`'s `plan_roster`](09-optimal-roster.md),
> which is implemented, so this is now the only missing piece.

### What does this compute?

One seat's best-affordable roster — `09`'s [`plan_roster`](09-optimal-roster.md)
— re-run under N seeded price scenarios and printed side by side, so you can see
which buys hold up when the money lands differently than fair value. It is a
small, reproducible Monte Carlo over *price luck*: each column is one integer
seed, and the players that appear in every column are flagged as "robust buys."

### Why not just run `09` once?

Because `09` plans against the *current* board fair values — "the best roster
reachable if prices hold" — and prices rarely hold. A single plan tells you
nothing about how fragile it is: whether its top target is a buy you'd make in
any market, or one that only pencils out because this exact price sheet happened
to make him cheap. Running the same solve across several perturbed price sheets
turns that fragility into something you can read off the page.

### How does the price jitter actually work?

Every scenario starts from one shared base: `07`'s
[`price_board`](07-live-draft-board.md) is solved once at `--w-floor` (default
`1.0`, the pure-VORP board price) against the residual state, giving a board
price and a replacement level per position. Then, per seed, `jitter_prices`
perturbs every base price independently:

```
rng    = random.Random(seed)              # one RNG, seeded by the column's integer
factor = 1.0 + rng.uniform(-sigma, sigma) # drawn per player, in board-row order
price  = max(min_bid, round(base_price * factor))
```

So each player's price is scaled by an independent uniform draw on
`[1 − sigma, 1 + sigma]`, rounded to whole dollars and floored at `min_bid`.
`sigma` is the half-width of that band: `--sigma 0.15` is ±15%. Because the RNG
is seeded by the column's own integer and drawn in a fixed order, a given seed
always yields exactly the same jittered sheet — that is the whole reason for
naming seeds rather than taking an unseeded draw. `09` then plans against that
sheet (with `exclude_positions` and `fill_all=True`), and the columns are laid
out next to each other.

### What's a "robust buy"?

A player who surfaces as a *value* target — not a fill — in **every** seed's
plan. `robust_note` intersects the target sets across all columns; the survivors
are the picks price luck does not change your mind about. Fills (the cheap floor
bodies `fill_all` adds to complete the roster) are excluded from the
intersection, because they are `$1` slot-fillers, not convictions.

### What's the output, precisely?

A header (seat, budget left, snapshot), then one column per seed: its spend,
open-slot count and lineup points, its ordered value targets (name, position,
price, marginal points), its `fills`, and a `spend + reserve` / `lineup +gain`
footer. Below the table, one line: `Robust buys (in every seed): …`, or `none`.
The numbers are `09`'s own — this wrapper adds no valuation, only the price
perturbation and the layout.

### What does that look like in practice?

- **Wide `sigma`:** the columns spread apart — more price uncertainty admits
  more different shopping lists, and fewer buys survive all of them.
- **Narrow `sigma`:** the columns collapse toward the single fair-value plan,
  and most buys become robust.
- **Worked example:** seat 5 (`yidinghou`), `$129` left, frozen after pick 40,
  seeds `1,2,3` at `--sigma 0.03` (±3%), `DEF` excluded. Even at ±3% the greedy
  paths diverge — seed 1 opens on Saquon Barkley (`$32`, +90.3), seed 3 on Chase
  Brown (`$32`, +88.8) — but Chris Olave (WR, ~+55.3 pts, ~`$20`) is bought in
  all three columns, so the run ends in `Robust buys (in every seed): Chris Olave`.

### What if no buy is robust?

The output is `Robust buys (in every seed): none`, and that is a real finding,
not a failure: on a board deep at your open positions (a run of near-equal
receivers, say) small price moves swap one substitute for another, so no single
name survives every draw. The wrong reading is "the plan is worthless" — each
column is still a legal, best-affordable roster; what the empty set tells you is
that *which* players get there is price-sensitive, so stay flexible rather than
fixating on one target.

### What's the catch?

It inherits `09`'s catch — the plan is only as good as the prices it spends
against, and greedy is an approximation, not the exact knapsack — and adds one
of its own: the jitter is a **uniform ±sigma toy model of price luck, not a
calibrated forecast** of how the room will actually misprice players. Real
mispricing is correlated (a position runs hot together) and skewed; this draws
each price independently and symmetrically. Read the spread as "is my plan
fragile to prices moving at all," not as a probability distribution over
outcomes.

### Is it deterministic?

Yes, by construction: same seeds + same inputs (same draft file, `--after`,
`--sigma`, `--w-floor`, `--exclude`, `--me`) produce a byte-identical table,
every run — the compute is all Python, no model in the loop past the one shared
board solve. Re-running the same command reproduces the table exactly; do not
hand-edit the numbers. Note that a live `data/draft-<id>.json` grows as picks
come in, so pin `--after N` to freeze a snapshot.

---

## Reference

**Depends on:** [`09-optimal-roster.md`](09-optimal-roster.md)'s `plan_roster`
for each column's solve; [`07-live-draft-board.md`](07-live-draft-board.md)'s
`price_board` for the shared base prices and replacement levels; the league
config and `data/projections-2026.csv` (see [`../data/`](../data/index.md)) via
`vorp.csv_loader`; the [`roster-scenarios`](../../../.claude/skills/roster-scenarios/SKILL.md)
skill, which picks the arguments and runs it. **Implemented in:**
`python/scripts/roster_scenarios.py` (`jitter_prices` for the price model,
`build_state` for the residual replay, `_column` / `render` / `robust_note` for
the layout). **Done when:** re-running one command reproduces the table
byte-identical; each column is a legal `RosterPlan` (`spend + reserve <=
budget`); and the robust-buys line is exactly the set-intersection of the
columns' value targets.

| Input | Description |
| --- | --- |
| `draft_file` | a saved draft JSON (`data/draft-<id>.json`); replayed into a residual `LeagueState` |
| `--after N` | snapshot: replay only the first N picks (default: all of them) |
| `--seeds 1,2,3` | comma-separated integer seeds, one column each (default `1,2,3`) |
| `--sigma 0.15` | half-width of the ± price-jitter band, as a fraction (default `0.15` = ±15%) |
| `--me SEAT` | 1-based seat to plan (default: the draft file's own `me`) |
| `--w-floor 1.0` | dial for the base board price (`1.0` = pure VORP), passed to `07` |
| `--exclude DEF` | positions to leave out of the plan, passed to `09` (default `DEF`) |

| Output | Description |
| --- | --- |
| Per-seed column | `09`'s ordered value `targets` and `fills`, with spend, lineup points and reserve |
| Robust buys | value targets present in **every** seed's plan; `none` when the intersection is empty |
| Determinism | same seeds + inputs → byte-identical table |
