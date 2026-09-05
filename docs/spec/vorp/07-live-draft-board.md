# 07 · Live draft board (FAQ)

> **The pricing core is implemented.** `python/vorp/board.py` (`price_board`)
> exists, lifted out of `scripts/draft_demo.py`'s repricing logic and pinned
> by `python/tests/test_board.py`. The **live server** described in
> [`../board/`](../board/index.md) — ingestion, seat identity, the rendering
> contract, the scrubber, `python/scripts/draft_board.py` — is still not
> built; `price_board` has no HTTP surface yet.

### What does this compute?

The same blended price as `04`, but against the league that is actually left:
the players still on the board, the roster slots still open, and the money still
in the room. Every sale reprices everyone remaining.

### Why not just grey out the players who are gone?

Because a static price list is priced for a room that no longer exists. `04`
apportions `teams × budget` — $2400 across 192 spots — and the first sale
falsifies both numbers. Ten picks into an aggressive run the room is down to
$1821 for 182 spots, and a cheat sheet still quoting opening prices tells you to
pay $45 for a receiver the remaining money can only support at $41.

### So how does it actually work?

Three things change, and nothing else does:

```
pool     = teams · budget − Σ(actual sale amounts)
slots    = opening league slots, minus one per sale
pool of  = every player not yet sold
players
```

A sale consumes **one** slot at the seat that bought the player, by
[seats and sales](../league/03-seats-and-sales.md)'s matching rule. Then
`01`'s replacement level and `02`'s last-rostered level are re-solved over the
remaining players and remaining slots, and `progressive_blend` is re-run at
`w_floor`, at `1.0`, and at `0.0` — giving a fresh price, VORP $, and VOLR $ for
everyone left. The model is not modified; it is handed a smaller league.

### Where does the residual league state come from?

From [seats and sales](../league/03-seats-and-sales.md), which models the
league as seats holding real slots rather than per-team counts. That is what
makes a single sale expressible: it removes one slot from the league's open
list and its price from the pool. This board adds no state model of its own
— it hands that residual state to `04`'s pricing model and renders the
result.

### What's the output, precisely?

For every unsold player: a price, a VORP $, a VOLR $, and the drift from his
opening price. Plus the league's residual state — money spent, money left,
spots left, dollars per spot, and the value still on the board.

### What does that look like in practice?

- **The room overpays:** money leaves faster than value does, so every
  remaining player gets cheaper — the board is telling you to wait.
- **The room finds bargains:** the top ten backs go for $1 each and the pool
  barely moves while the value does; the best receiver left goes $46 → $56.
- **Sales tracking slots:** while each sale consumes a slot at its own
  position, the bar doesn't move at all — the 24th-best back is still the
  marginal back. Early-draft price movement is almost entirely the money pool,
  not the bars.
- **Worked example:** the first ten running backs go for $15 over their opening
  prices. The pool drops from $2400 to $1821 and 10 slots come off, but RB's
  replacement level holds at 137.9 — so Ja'Marr Chase, untouched at 256.6
  points and unchanged against his bar, reprices from $45 to **$41**.

### What happens when a position sells past its own starting slots?

Its bar starts to move, because further sales there consume flex slots that the
other flex-eligible positions were counted against. Twelve tight ends sold
leaves TE's replacement level exactly where it opened at 129.5; the thirteenth
drops it to 126.3. The wrong answer is to treat a position with no concrete
slots left as unplayed — `04` already covers that: the ramp collapses onto the
last-rostered bar and it is priced as the pure bench position it has become.

### What's the catch?

Every reprice assumes the rest of the room will spend its remaining money
rationally — which is exactly the assumption the sale you just watched
violated. When the room overpays for a back, the board dutifully marks
everyone else down to fit the smaller pool, as though the next hundred picks
will be disciplined. If the room keeps overpaying, the board keeps marking
down and keeps being wrong in the same direction. It is a fair-value model
re-solved on new information, not a forecast of what the room will actually do
next.

### Does this hold up on a live draft?

Repricing runs server-side on every sale, so the page holds no copy of the
model. Sales arrive from a manual entry pane today and from Sleeper's draft
API later — picks carry `metadata.amount`, the real sold price, which is the
input this needs.

---

## Reference

**Depends on:** [the league model](../league/index.md) for the residual league
state, `01-calculating-replacement.md` and `02-value-over-last-rostered.md` for
the two bars, `04-blended-bar-pricing.md` for the pricing model.
**Implemented in:** `python/vorp/board.py` (`price_board`), over
`python/vorp/league/teams.py`; served by `python/scripts/draft_board.py`.
**Done when:** with nothing sold the
board reproduces `data/blended-price-2026.json`'s prices exactly, one sale
removes exactly one player and one slot from the priced board, and the laws in
`05` still pass at a mid-draft state.

| Input | Description |
| --- | --- |
| Sold set | `{player_id: amount}` — the actual price paid, not the projection |
| Opening league config | `teams`, `budget`, `min_bid`, slot template |
| Player pool | the same projections `04` prices, minus the sold |
| `w_floor` | `04`'s one dial; fixed for a session, no slider on a live board |

| Output | Description |
| --- | --- |
| Price, per unsold player | whole dollars `>= min_bid`, against the residual pool |
| VORP $ / VOLR $ | the same two ends of the dial, re-solved |
| Drift | price minus opening price — what the room has done to him |
| Residual league state | money left, spots left, $/spot, value left |
| Levels, per position | replacement and last-rostered, as they stand now |
| Reconciliation | prices sum to exactly `teams × budget − spent` |
