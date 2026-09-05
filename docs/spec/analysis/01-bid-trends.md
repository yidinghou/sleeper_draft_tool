# 01 · Bid-log trends by seat (FAQ)

### What does this compute?

For each seat (team) in a finished or in-progress auction, a fixed set of
counting stats — wins, dollars spent, bids placed, distinct auctions entered,
win-rate on those entries, nominations opened, top-3 positional spend, and the
single largest bid — followed by a **field-relative behavioral read**: a short
list of labels (`efficient closer`, `volume accumulator`, `heavy nominator`,
`pays up` / `bargain buyer`, `<pos>-concentrated`, `very selective`) earned by
where the seat lands against the room's own medians. It is descriptive: it
reports how the room bid, and prescribes nothing.

### Why not just rank seats by wins or by total spend?

Because everyone in a $200 auction spends almost exactly $200 — the interesting
signal isn't *how much*, it's *how*. Ranking by an absolute number also can't
answer "aggressive relative to whom": 18 nominations is heavy in a passive room
and ordinary in a busy one. So the labels are computed against this room's
medians, not fixed cutoffs, which is what makes them actually separate seats
instead of bucketing everyone the same.

### How does it actually work?

It walks each player's bid sequence in the bid log once, attributing each bid to
its seat, then labels every seat against the room's medians:

```
for each player's [bid, bid, …]:
  every bid            → seat.bids++;  first time this seat appears → seat.auctions++
  first bid (i === 0)  → seat.openings++          (the nomination)
  bid > seat.maxBid    → seat.maxBid = {amount, player}
  last bid in sequence → that seat WON: seat.wins++, seat.spent += amount,
                         seat.posSpend[pos] += amount

convOf        = wins / auctions        dollarsPerWin = spent / wins
topShare      = max(posSpend) / spent

labels (field-relative unless noted):
  convOf       >= medConv  * 1.25 → "efficient closer (high win rate on entries)"
  wins         >= medWins  * 1.4  → "volume accumulator (wins a lot)"
  openings     >= medOpen  * 1.4  → "heavy nominator"
  dollarsPerWin>= medDpw   * 1.2  → "pays up ($/win high)"
  dollarsPerWin<= medDpw   * 0.8  → "bargain buyer ($/win low)"   (else-branch)
  topShare     >= 0.55            → "<topPos>-concentrated (NN% of spend)"  (absolute)
  auctions     <= medAuct  * 0.6  → "very selective (few auctions entered)"
  no label matched                → "balanced / middle-of-pack"
```

The winner of an auction is taken to be the **last bidder** in that player's
sequence, cross-checked against the draft file's `draft_slot` and `amount`.
Position for each sold player comes from the draft file, falling back to the
`boberto-2026.csv` export; seat names come from the draft file's `seat_names`.
The whole thing is a single pass with no model in the loop, so it is
deterministic for a given file snapshot.

### What's the output, precisely?

Two blocks to stdout. First a stats table, one row per seat sorted by seat
number, with `wins`, `spent`, `bids`, `auct` (distinct auctions entered), `win%`
(`wins/auctions`), `open` (nominations), and top-3 `position:dollars`. Then the
behavioral read: one entry per seat with the headline numbers (`W`, `$`, win
rate, `$/win`, noms, top bid + player) and the `→` list of earned labels. The
reader's own seat (`draft.me`) is marked `*` in the table and `(you)` in the
read.

### What does that look like in practice?

- **One-position build:** a seat that sinks most of its money into a single
  position clears the absolute `topShare >= 0.55` bar and gets tagged
  `<pos>-concentrated` — e.g. `jvaldillez` at 93% WR spend.
- **Busy but losing:** a seat with many nominations but a low close rate lands
  `heavy nominator` without `efficient closer` — it ran up prices it didn't win.
- **Worked example:** in the `1399388062693273600` mock (192 players sold),
  seat 5 `yidinghou` went 12 wins on 22 auctions entered → win rate `12/22 =
  0.545`. The room's median win rate is `0.364`, so the `efficient closer`
  threshold is `0.364 × 1.25 = 0.455`; `0.545 ≥ 0.455`, so it earns
  **`efficient closer`**. It also entered only 22 auctions against a median of
  `37.5`; the `very selective` bar is `37.5 × 0.6 = 22.5`, and `22 ≤ 22.5`, so
  it also earns **`very selective`** — the printed read is exactly
  `efficient closer (high win rate on entries); very selective (few auctions entered)`.

### What happens to a seat whose name is missing, or a player not in the export?

A seat with no entry in `seat_names` prints as `#<seat>` rather than crashing —
the labels still compute off its numbers. A sold player absent from both the
draft file and the CSV gets position `?`, so its winning dollars land in a `?`
bucket in `posSpend`; that's a data-coverage gap in the export, not a real
position, and it never blocks the run.

### What's the catch?

The labels are relative to the room, so they move as the room fills and between
drafts: a `heavy nominator` is heavy *relative to these eleven others*, not by
any absolute standard, and the same seat re-run at a different point in the same
draft can gain or lose a label as the medians shift. The one exception is
`<pos>-concentrated`, whose `0.55` bar is absolute — so it is the only label
that means the same thing across rooms.

### Does it hold up while the draft is still live?

Yes, but each run is a snapshot. The live draft file grows as picks come in, so
the "players sold" count and every stat climb between runs; the computation is
deterministic for the file *as read*, so re-run to refresh and lock a final read
once picks stop climbing. The bid ladder it consumes is the one the board
server's ingestion reconstructs — see `../board/01-live-data-ingestion.md`.

---

## Reference

**Depends on:** a saved bid log `data/bid-log-<id>.json` (per-player bid
sequences, reconstructed by the board's ingestion — `../board/01-live-data-ingestion.md`),
its draft file `data/draft-<id>.json` (sold picks, `seat_names`, `me`), and the
`data/boberto-2026.csv` export for player name/position fallback.
**Implemented in:** `scripts/analyze-bids.ts` — a single self-contained pass; no
shared library, no model. Run with `npx tsx scripts/analyze-bids.ts [draftId]`
(or plain `node scripts/analyze-bids.ts [draftId]` on Node 22+), defaulting to
draft `1399388062693273600`. **Done when:** for a given file snapshot the stats
table and behavioral read regenerate byte-identical, the winner of each auction
matches the draft file's `draft_slot`/`amount`, and every seat earns at least
one label (`balanced / middle-of-pack` when no field-relative bar is cleared).

| Input | Description |
| --- | --- |
| `data/bid-log-<id>.json` | `{ player_id: [{ seat, amount }, …] }` — each player's bid ladder, in order |
| `data/draft-<id>.json` | `{ me?, seat_names?, picks: [{ player_id, amount, draft_slot, pick_no, position }] }` |
| `data/boberto-2026.csv` | export; `player_id,player,position,…` header — name/position fallback |
| `[draftId]` arg | which file pair to read; defaults to `1399388062693273600` |

| Output | Description |
| --- | --- |
| Stats table | per seat: `wins`, `spent`, `bids`, `auct`, `win%`, `open`, top-3 position spend |
| `wins` / `spent` | last-bidder count, and sum of those winning amounts |
| `auctions` | distinct players the seat bid on at all |
| `openings` | times the seat placed the first (`i === 0`) bid on a player |
| `maxBid` | the seat's single largest bid amount, and on whom |
| Behavioral read | per seat: headline numbers + field-relative labels; own seat marked `(you)` |
