# 03 · The rendering contract (FAQ)

### What does this compute?

The `/state.json` payload and the three-slide deck it drives. The payload is the
whole board — priced pool, seats, divisions, the on-the-block player, the draft
log — computed server-side by `build_payload`. The deck
(`templates/board_slides.html`) renders it and nothing else: the JavaScript holds
**no** copy of the pricing model, so there is no second implementation to keep
honest.

### Why not compute anything in the browser?

Because the pricing model (`../vorp/07-live-draft-board.md`) lives in one Python
process, and every dollar figure on the page traces back to a `price_board`
solve over the residual league. Porting even part of it to JS would mean two
implementations that drift. The one thing the client does compute — the roster
slot-fill — is a deliberate, tested mirror of the Python matching, not a second
opinion (see below). Everything else it reads straight off the payload.

### How does it actually work?

`build_payload` runs `price_board` on the residual `LeagueState`, then folds the
result into named blocks the three slides consume. The deck is `#s-live`,
`#s-market`, `#s-rosters`, switched by the floating nav (or keys `1`/`2`/`3`,
arrows). `renderAll` fans the payload out to per-region render functions; a
poll loop refetches `/state.json` at the adaptive cadence and re-renders only
when the JSON text changes.

**Slide 1 (Live)** — a unified header (`renderHeader`, shared verbatim with
slide 2) carrying the on-block player as a hero tile, a bidding/worth split
tile, and per-seat "worth to each seat" mini-bars ordered by division. The
**Worth blend bar** places up to five dollar figures on a bargain→fair→overpay
gradient: the Sleeper `$` anchor on top as the real-market price, Boberto `$`
and VORP `$` (the "twins") riding above the bar as fair value, and Wk1-3 `$` and
VOLR `$` dropping below — three fixed vertical bands and greedy tiering keep the
labels from ever colliding. Below the header: the **buying-power + bid-activity
bars** (`renderPower`) — one bar per seat, height scaled to `max_bid`, gold-fill
fading by how recently the seat last led the bidding, with a lead-count pill;
the **draft-state-by-position** table; the selected/high-bidder roster cards; and
the **run-pressure** cards.

**Slide 2 (Market)** — the same header over the **pool matrix**
(`renderMatrix`): every priced player as a row, with a sortable **Bargain**
column (blended fair value minus Sleeper `$`) and a per-seat **bid matrix** —
what each of the twelve seats would bid, with the likely winner, the price-setter
(2nd bid), and the expected winning price (`2nd + $1`) marked per row.

**Slide 3 (Rosters)** — one band per division (mine first, outlined), each a
four-card grid. Each card runs `fillSlots`, an **in-browser bipartite slot-fill**
that seats a team's bought players into its starting slots to maximize projected
points via Kuhn's augmenting paths, benching the leftovers. This mirrors
`../league/02-slot-assignment.md`'s matching exactly — bench slots are held out
of the match on purpose so a QB is never parked on the bench to seat a lower WR
in SUPER_FLEX. The visual system is the golden POC `poc/board-slides-golden-new.html`;
the worth bar, buying-power bars, and roster highlight trace to
`poc/worth-blendbar-color.html`, `poc/buying-power-bidders.html`, and
`poc/selected-roster-highlight.html`.

### What's in the payload, precisely?

Top-level keys include `pool`, `spent`, `spots_left`, `vorp_rate`, `paid_rate`,
`starting_slots_left`, `levels` (per-position replacement/last-rostered),
`block`, `bid_ladder`, `bid_book`/`bid_meta`, `seats`, `divisions`,
`seat_order`, `state_table`, `matrix`, `my_plan`, `log`, `players`, and `view`
(`{pick, total, live}`). `block` is folded with its own `market`, `vorpD`,
`volrD`, `wk3VorpD`, and per-seat `bids` so the header renders from one source.
Each `seats[i]` carries `budget`, `max_bid`, `have`, `division`, and roster
`lines` (each line's opening `price`, for the over/under-pay tags).

### What does that look like in practice?

- **Manual bar override:** the draft-state table's "Bar (pts)" column is a
  slider per position; dragging it (`barOverride`) recomputes VORP got/left
  against the dragged bar client-side, off `state_table.bar` and `drafted_pts`
  — no server round-trip.
- **On-block emphasis:** the block player is forced into the matrix solve and
  floated to the top of the pool list, so his per-seat worth always exists even
  when he isn't a top-priced row.
- **Worked example:** the mock fixture has Trey McBride on the block at TE for a
  `$14` current bid held by seat 9. The header shows my max bid `$136` (seat 2's
  cap), a Sleeper anchor of `$34`, VORP `$24` / VOLR `$20` / Wk1-3 `$31`, and a
  per-seat worth row that reads `$23` for **all twelve** seats — no seat holds a
  TE yet, so every seat values him at the same board price, which is exactly what
  `test_block_carries_the_unified_header_fields` checks (12 integer bids, equal
  to the matrix row's).

### What does the header show when nobody is on the block?

A single hero tile reading "Nobody on the block / waiting on a nomination" — no
worth bar, no seat bars. `block` is `null` between nominations, and every render
function guards on it, so the deck degrades to the pool, rosters, and draft log
without erroring.

### What's the catch?

The client is a pure renderer, which means it is only ever as fresh as the last
`/state.json` it received — there is no client-side prediction, so during the
fast-cadence window a raise shows up one poll late, and any figure the payload
didn't carry simply isn't on the page. The single exception, `fillSlots`, is a
hand-maintained JS port of the Python matching; it is tested to agree, but it is
still the one place two implementations could drift.

### Does the display order ever change the underlying data?

No. `seat_order` (and the roster slide's `bubbleLead`) reorder only which column
or card is drawn where; the per-seat `bids` arrays stay seat-indexed, so reading
`bids[sid]` through the display order yields each seat's own value. Reordering is
display-only — asserted by `test_divisions_group_seats_mine_first_when_identity_present`.

---

## Reference

**Depends on:** `build_payload` in `python/scripts/auction/draft_board.py` (which calls
`price_board`, `seat_values`/`price_from_value`, and `plan_roster`);
`../vorp/07-live-draft-board.md` for the prices, `../vorp/08-seat-value.md` for
the per-seat bids, `../league/02-slot-assignment.md` for the matching the client
mirrors. **Implemented in:** `python/scripts/auction/draft_board.py`
(`build_payload`, `seat_matrix`, `block_info`, `draft_state_table`,
`player_pool`, `league_payload`) and `python/scripts/auction/templates/board_slides.html`
(`renderHeader`, `renderPower`, `renderStateTable`, `renderMatrix`,
`renderRosters`, `fillSlots`). **Done when:** the payload reconciles to the
residual pool, the block carries `{market, vorpD, volrD, wk3VorpD, bids}` with
one integer bid per team, the matrix is well-formed, and the roster template
includes the SUPER_FLEX the golden POC omitted — see
`test_block_carries_the_unified_header_fields`,
`test_seats_carry_names_and_the_matrix_is_well_formed`, and
`test_targets_include_the_superflex_the_golden_omitted`.

| Input | Description |
| --- | --- |
| residual `LeagueState` | picks replayed into seats + pool, from ingestion |
| `price_board` output | prices, VORP $ / VOLR $, levels, `vorp_rate` per player |
| seat values | `seat_values`/`price_from_value` — per-seat bid for each pool row |
| `nomination` | the on-the-block player + current high bid (or empty) |

| Output | Description |
| --- | --- |
| `block` | on-block player, folded with market $, VORP $/VOLR $, per-seat `bids` |
| `matrix` | pool rows with Bargain, twin $ columns, and per-seat bid matrix |
| `state_table` | per-position drafted/spent/paying + `bar` and `drafted_pts` |
| `seats` / `divisions` / `seat_order` | rosters, division bands, column order |
| `players` / `my_plan` / `log` / `view` | pool list, best-affordable plan, log, live marker |
