# 05 · Principles (FAQ)

### What does this compute?

A pass/fail matrix: every registered valuation model against every principle a
price list has to satisfy. It turns "which model is better" from an argument
into a table.

### Why not just compare models on how close they land to the market?

Because market error alone ranks a broken model above a sound one whenever the
break happens to cancel out. The two-lens dial had the second-best market error
on this board and still put a worse player above a better one at the same
position — a defect no amount of calibration excuses. Laws catch that;
closeness-to-market can't.

### So how does it actually work?

A model is any function `(players, config) -> Valuation`, and a principle is
any function `(model, context) -> Finding`. Principles receive the model
itself rather than one of its outputs, which is what lets them re-run it
against a different board — shifted projections, a mid-draft state — instead
of only inspecting a single answer. `run()` memoizes by board identity so the
suite pays for each distinct solve once rather than once per principle.

### What separates a law from a calibration?

A **law** must hold or the output isn't a price list, and it is pass/fail. A
**calibration** says the model matches the world, is graded rather than
pass/fail, and reasonable models disagree there — disagreeing with the market
is frequently the entire point of building a model. There are ten laws and
three calibrations.

### What's the output, precisely?

Per model, a `Finding` for each principle: `passed`, a one-line `detail`, and
a `measure` worth trending across models. `scripts/principles.py` prints the
laws as a pass/fail grid with a score, the calibrations as bare measurements.

### What does that look like in practice?

- **A model with no baseline:** prices raw production, so adding a constant to
  every projection moves its prices — `baseline-not-points` fails.
- **A model that blends prices:** monotonic on most positions, crossing on the
  thin one — `monotonic` fails with the offending pair named.
- **A model whose ramp is too steep:** `ramp-slope` fails before any board is
  priced, because the defect is in the shape rather than the data.
- **Worked example:** on the 2026 board every shipped model scores 10/10 laws;
  `points_proportional` scores 9/10, failing only `baseline-not-points`, with
  126 prices moved under a +50 shift.

### What if every model passes every law?

Then the suite isn't testing anything yet. The first eight laws written here
passed a deliberately broken strawman 8/8, which is what exposed that none of
them encoded *why* a baseline exists — the gap that became
`baseline-not-points`. A strawman that passes is a finding about the suite,
not a compliment to the strawman.

### What's the catch?

The calibration thresholds are arbitrary. `market-mae ≤ 4.0`, `bench-spend`
within `$6`, `top-price` within `$15` — none of those numbers were derived
from anything, and they're only reported rather than enforced. The laws are
the part worth trusting.

### Does the mid-draft law prove a model works live?

No. It checks two states built from one friendly assumption — sales in market
order, starting slots consumed before bench — and a real draft doesn't
cooperate. It is strong enough to have caught the collapse where a position's
consumed starting slots made it unpriceable, and it should not be read as more
than that.

---

## Reference

**Depends on:** `python/vorp/models.py` for the model protocol and registry,
league config, and the projections CSV for market values. **Implemented in:**
`python/vorp/principles.py` (runner and principles), `python/scripts/auction/principles.py`
(report). **Done when:** the strawman fails `baseline-not-points` and passes
nothing it shouldn't, `progressive_blend` passes every law, and the seam
regression fixture in `tests/test_principles.py` shows price-blending failing
`monotonic` where bar-blending passes.

| Input | Description |
| --- | --- |
| Model | `(players, config) -> Valuation`; anything in `models.REGISTRY` |
| Context | the board, the league config, and the market's own auction values |
| Principle | `id`, `kind` (law or calibration), a one-line statement, and a check |

| Output | Description |
| --- | --- |
| Laws (10) | reconciles, monotonic, floor, fills-rosters, no-phantom-positions, no-streamed-depth, informative-ordering, baseline-not-points, ramp-slope, mid-draft |
| Calibrations (3) | market-mae, bench-spend, top-price — measured and reported, never enforced |
| `Finding` | `passed`, `detail`, and a `measure` comparable across models |
| `Report` | all findings for one model, plus `laws_passed` / `laws_total` |
