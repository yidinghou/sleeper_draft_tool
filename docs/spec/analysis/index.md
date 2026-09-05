# Draft-trend analysis — WIP

> **Work in progress — not yet implemented.** `scripts/analyze-bids.ts` and the
> [`bid-trends`](../../../.claude/skills/bid-trends/SKILL.md) skill it's run
> through don't exist in this repo yet. It also depends on a saved bid log
> (`data/bid-log-<id>.json`) reconstructed by the board server's ingestion
> ([`../board/01-live-data-ingestion.md`](../board/01-live-data-ingestion.md)),
> which is itself not yet implemented.

## What this covers

Reading a draft *after* (or partway through) it happens, rather than planning
the next bid. These tools take a saved bid log and its draft file and describe
how the room actually behaved — who accumulated, who nominated, who paid up, who
bought bargains, who concentrated on one position — by walking the bid ladder
once and labeling each seat against the room's own medians.

This is deliberately descriptive, not prescriptive. It does not price players,
does not recommend bids, and has no model in the loop: for a given file snapshot
it is a deterministic summary of what the bids say. Because a live draft file
grows as picks come in, each run is a snapshot in time — re-run to refresh, lock
a final read once picks stop climbing.

The forward-looking, prescriptive counterpart — planning one seat's own best
affordable roster under seeded price scenarios — is not here; it lives at
`../vorp/09b-roster-scenarios.md`.

## The specs

| | What it covers |
| --- | --- |
| [01 · Bid-log trends by seat](01-bid-trends.md) | Per-seat counting stats plus a field-relative behavioral read (efficient closer, volume accumulator, heavy nominator, pays-up / bargain buyer, position-concentrated, selective) |

Run it via the [`bid-trends`](../../../.claude/skills/bid-trends/SKILL.md) skill,
which picks the draft id and runs `scripts/analyze-bids.ts` for you; see
[guide.md](guide.md) for the raw reproduction steps. The bid ladder it reads is
reconstructed by the board server's ingestion (`../board/01-live-data-ingestion.md`).
