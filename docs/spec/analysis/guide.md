# Draft-trend analysis — reproduction guide — WIP

> **Work in progress — not yet implemented.** `scripts/analyze-bids.ts` doesn't
> exist yet; see the [module index](index.md) for status.

How to regenerate the per-seat bid-log trend analysis (`docs/spec/analysis/01-bid-trends.md`)
from scratch.

## Prerequisites

Three files in `data/`, all keyed by the same draft id:

- **`data/bid-log-<id>.json`** — the per-player bid ladder,
  `{ player_id: [{ seat, amount }, …] }`, produced by the board server's
  ingestion as bids stream in (`../board/01-live-data-ingestion.md`). Seats are
  1-indexed (1..12); bids are in the order placed.
- **`data/draft-<id>.json`** — the sold-picks record:
  `{ me?, seat_names?, picks: [{ player_id, amount, draft_slot, pick_no, position }] }`.
  `seat_names` is keyed **0-indexed** (0..11) while seats are 1-indexed, so the
  script shifts by one; `me` marks the reader's own seat.
- **`data/boberto-<season>.csv`** — the projections export (e.g.
  `data/boberto-2026.csv`), header `player_id,player,position,…`. Used only as a
  name/position fallback for the positional-spend join and the top-bid label.

Node 22+ (strips TypeScript natively), or `tsx` via the repo's dev
dependencies (`npm install`).

## Run it

From the repo root:

```
npx tsx scripts/analyze-bids.ts [draftId]
```

or, on Node 22+, with no dependencies at all:

```
node scripts/analyze-bids.ts [draftId]
```

`[draftId]` is optional and defaults to `1399388062693273600` (the bundled mock
draft). Pass another id to point at a different `bid-log-<id>` + `draft-<id>`
pair. Both files must exist for that id or the read throws.

## Expected output

Two blocks to stdout. First a stats table — one row per seat, sorted by seat
number, own seat marked `*`:

```
Bid-log trends — draft 1399388062693273600  (192 players sold)

team           wins  spent  bids  auct  win%  open  top position spend
--------------------------------------------------------------------------------------
...
yidinghou *      12   $196    24    22   55%    13  RB:94 QB:54 WR:45
...
```

Then the field-relative behavioral read — headline numbers and a `→` list of
labels per seat, own seat marked `(you)`:

```
  yidinghou (you): 12W $196, 55% win rate, $16.3/win, 13 noms, top $58 (Jahmyr Gibbs)
      → efficient closer (high win rate on entries); very selective (few auctions entered)
```

The labels are earned against the room's medians (`efficient closer`,
`volume accumulator`, `heavy nominator`, `pays up` / `bargain buyer`,
`<pos>-concentrated`, `very selective`, else `balanced / middle-of-pack`); the
exact thresholds are in `01-bid-trends.md`.

## Gotchas

- **Snapshot in time.** A live draft file grows as picks come in, so the
  "players sold" count and every stat climb between runs. The output is
  deterministic for the file *as read* — re-run to refresh, and lock a final
  read once picks stop climbing.
- **Field-relative labels shift with the room.** A `heavy nominator` is heavy
  relative to these eleven other seats, not by any fixed cutoff, so the same
  seat can gain or lose a label as the medians move. Only `<pos>-concentrated`
  (absolute `0.55` of spend) means the same thing across drafts.
- **Missing names / players.** A seat absent from `seat_names` prints as `#<seat>`;
  a sold player absent from both the draft file and the CSV lands its dollars in
  a `?` position bucket. Neither blocks the run.
- **Winner = last bid.** The auction winner is the last bidder in each player's
  sequence, cross-checked against the draft file's `draft_slot`/`amount`; a
  mismatch there is the first thing to check if a seat's `wins`/`spent` look off.
