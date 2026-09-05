# VORP (Value Over Replacement Player)

## What VORP is

A player's worth isn't his raw projected points — it's how many points he
adds **above what a freely-available replacement at his position** would
score. Replacement level is not the worst player in the league; it's the
best player left after everyone who structurally needs that position has
one — the player a dollar actually buys.

```
VORP = max(0, player's projected points − replacement level at his position)
```

Floored at zero: nobody is worth less than replacement, because you'd never
actually field someone worse than the freely-available option.

## Static VORP

**Static VORP** is VORP computed once, at the opening bell, against the
pre-draft board — before any picks have happened. It uses:

- the league's structural per-position demand (how many bodies of each
  position the league's roster template wants, in total, across every seat)
- the full, un-drafted player pool

## Worked example

Say a league needs 12 tight ends total (across every seat, once), and the
tight end board, ranked by projected points, looks like:

| Rank | Player | Points |
| --- | --- | --- |
| 1 | TE A | 220 |
| 2 | TE B | 200 |
| 5 | TE C | 175 |
| 12 | TE L | 141 |
| 13 | TE M | 140 |
| 20 | TE T | 110 |

With demand for 12 tight ends, replacement level is the **13th** tight end
— the first one past the league's need — so replacement level = 140.

| Player | Points | Static VORP |
| --- | --- | --- |
| TE A | 220 | 80 |
| TE B | 200 | 60 |
| TE C | 175 | 35 |
| TE L | 141 | 1 |
| TE M | 140 | 0 (he *is* replacement) |
| TE T | 110 | 0 (floored — raw margin is negative) |

This is the number a static, pre-draft cheat sheet ranks players by.

## The specs

| | What it covers |
| --- | --- |
| [01 · Calculating replacement level](01-calculating-replacement.md) | The league-wide optimal fill, and the bar it leaves behind at each position |
| [02 · Value over last rostered](02-value-over-last-rostered.md) | The same fill over every roster spot, plus the streaming and flex-peer corrections |
| [03 · VORP $ and VOLR $](03-vorp-to-bid.md) | Two whole-budget lenses, side by side, and why they deliberately produce no single bid |
| [04 · Blended-bar pricing](04-blended-bar-pricing.md) | The shipped price: one sliding bar per position, monotonic by construction |
| [05 · Principles](05-principles.md) | The laws every model has to satisfy, and the harness that runs them |
| [The league model](../league/index.md) | The substrate: the roster template, the slot-assignment engine, and seats holding real slots so a single sale is expressible |
| [07 · Live draft board](07-live-draft-board.md) | **WIP** — the same price, re-solved against the players, slots and money actually left |
