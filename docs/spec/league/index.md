# The league model

## What this models

A fantasy auction league, as three layers that build on each other:

1. **The template** — the rules every seat is bound by: how many teams, how
   much budget, and one team's worth of roster spots by position, including
   flex. Frozen once the draft is created.
2. **The engine** — a generic bipartite match between players and roster
   slots, position-eligibility aware, used to answer "who actually makes the
   roster" for any pool of players and any pool of slots.
3. **The seats** — the template applied to real teams, holding real money and
   real players, one sale at a time. This is what turns "2 RB per team" into
   192 individual slots a single sale can remove one of, and it's what every
   VORP model in `../vorp/` is ultimately a fill over.

## Why three layers instead of one state object

Each layer answers a different question and changes at a different rate.
The template answers "what does this league's roster look like" and never
changes mid-draft. The engine answers "given these players and these slots,
who's selected" and doesn't know what a team or a sale is at all — it's the
same code whether it's filling the whole league's demand or one seat's.
The seats answer "who has bought what, and what's left" and are the only
layer that mutates, once per sale. Keeping them separate is what let the
seats layer replace a `count × teams` approximation with real per-team slots
without touching the engine at all.

## The specs

| | What it covers |
| --- | --- |
| [01 · The roster template](01-roster-template.md) | The frozen per-seat rules: positions, flex eligibility, bench, and what a league "plays" |
| [02 · Slot assignment](02-slot-assignment.md) | The shared matching engine: players in, slots in, an optimal fill out |
| [03 · Seats and sales](03-seats-and-sales.md) | Real teams holding real slots, so a single sale is expressible |

Consumed by `../vorp/01-calculating-replacement.md`, `../vorp/02-value-over-last-rostered.md`,
and `../vorp/07-live-draft-board.md`.

To rebuild this module from scratch in dependency order, see the
[reproduction guide](guide.md).
