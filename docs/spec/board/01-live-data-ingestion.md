# 01 · Live data ingestion (FAQ)

### What does this compute?

The bridge between a running auction and the pricing core. It turns a draft —
from a local mock file, a polled Sleeper draft, or a pasted pick list — into
the residual pick set that `../vorp/07-live-draft-board.md`'s `price_board`
reprices on, and serves the result over stdlib HTTP. Nothing here prices
anything; it feeds the model a smaller-and-smaller league as picks land.

### Why not just fetch Sleeper's draft once and render it?

Because Sleeper exposes only the **current** high bid on the player on the
block — never the ladder that got there — and a single fetch of a live auction
is stale the moment it lands. A raise you miss can't be re-fetched, its CDN
caches `/draft` responses by hours, and a `draft_order` that isn't seeded yet
names nobody. Ingestion exists to paper over all four: it polls, it accumulates
the ladder from its own poll history, it cache-busts every request, and it
fills unseeded seats so the board always looks live.

### How does it actually work?

Three source modes, mock-first, switchable at runtime through `POST /source`
(the landing page's target) with no restart:

```
--picks-file mock.json   re-read the file whenever its mtime changes, so a
                         hand-edited pick list moves the board live (the
                         testable path; mode = "file")
--draft-id <id>          a background thread polls Sleeper; mode = "draft"
(inline paste)           POST /source {"picks": [...]}; mode = "inline"
```

In `draft` mode the poller runs a **cheap** poll of `/draft` and computes a
`draft_fingerprint` — `status | nominated_player_id | highest_offer |
offering_slot | last_action_at`. Only when that string changes does it pay for
the **expensive** `/draft/{id}/picks` refetch (`poll_sleeper_once`). Every
poll also appends the observed high bid to `data/bid-log-<id>.json`
(`_append_bid_log`): Sleeper gives one rung at a time, so the ladder is
reconstructed from whatever the poller happened to see across polls, and a rung
is appended only when it differs from the last recorded one. The whole draft is
mirrored to `data/draft-<id>.json` (`_save_draft`, atomic temp-file replace) so
history survives a restart and can be replayed offline — the saved envelope is
the same shape `--picks-file` reads, so it opens directly.

Both `sleeper_client.py` reads go through `_get`, which appends `?_cb=<epoch_ms>`
to defeat the CDN. That client is a read-only stdlib-`urllib` mirror of
`src/sleeper.ts`, so the pricing process has no second language runtime.

### What's the output, precisely?

The HTTP surface. `GET /state.json` returns the whole board payload (shape
documented in `03-rendering-contract.md`); `GET /state.json?upto=<n>` returns a
frozen historical frame (`04-time-travel-scrubber.md`). `GET /config` reports
`draft_id`, `season`, `mode`, `kind`, `my_seat`, and `seat_users`. `POST /source`
repoints the board. `GET /health` returns `ok`. `GET /bid-log.jsonl` streams
one denormalized NDJSON row per bid rung — player, position, seat manager,
amount, and who outbid it — so an LLM can read the ladder without stitching the
book to the player-meta map itself.

### What does that look like in practice?

- **A pick lands:** the fingerprint changes, `/picks` is refetched, the new
  sale removes one slot and its price from the residual state, and every
  remaining player reprices on the next `/state.json`.
- **Nobody bids for a while:** the fingerprint holds, so the poller keeps
  hitting the cheap `/draft` and never pays for `/picks` — the board sits still
  for free.
- **Worked example:** the mock fixture's 14 picks total `61+58+50+…+35 = $602`.
  Against `12 × $200 = $2400`, the payload reports `spent = 602`, `pool = 1798`,
  and `spots_left = 12 × 16 − 14 = 178` — exactly what
  `test_pool_reconciles_to_the_residual_league` asserts.

### What happens to a pick with no buyer recorded?

A manually-entered pick can carry no `draft_slot`. `build_state` lands it on the
synthetic `UNKNOWN_SEAT` (`seat_id = None`) rather than guessing a buyer: the
sale still leaves the pool and the board still reprices, but no real seat is
charged for it. The wrong answer would be attributing it to seat 0.

### What's the catch?

The reconstructed bid ladder is only ever as complete as the poll history that
observed it. Sleeper never serves the full ladder, so a rung raised and
outbid between two polls is simply never recorded — the ladder in
`data/bid-log-<id>.json` is a sample of the bidding, not a transcript of it.
On a fast auction the slide-1 bid timeline can miss intermediate rungs entirely.

### Does the poll rate keep up with live bidding?

Yes, adaptively. The poller (and the client) run at the idle cadence — `0.75s`
— but drop to `0.2s` the moment a player is on the block, because latency is
only felt during active bidding and a missed raise can't be recovered. Both
rates are localhost-only, so the fast cadence is essentially free.

---

## Reference

**Depends on:** `python/vorp/sleeper_client.py` for the four read-only Sleeper
calls (`fetch_draft`, `fetch_draft_picks`, `fetch_league_users`,
`draft_fingerprint`/`parse_nomination`), which mirror `src/sleeper.ts`;
`python/vorp/board.py`'s `price_board` for the actual repricing
(`../vorp/07-live-draft-board.md`); `python/vorp/league/config.py` for
`LEAGUE_CONFIG`. **Implemented in:** `python/scripts/auction/draft_board.py` — the
`Board` class (`set_source`, `refresh_from_file`, `poll_sleeper_once`,
`_append_bid_log`, `_save_draft`, `load_saved_draft`, `build_state`) and the
`make_handler` HTTP routes, with `poller` driving the adaptive cadence.
**Done when:** the payload reconciles to the residual pool, `spots_left` drops
by exactly one per pick, and a saved `data/draft-<id>.json` replays byte-for-byte
through `--picks-file` — see `test_pool_reconciles_to_the_residual_league`,
`test_saved_draft_replays_as_picks_file`, and
`test_save_and_load_saved_draft_round_trip`.

| Input | Description |
| --- | --- |
| `--picks-file <path>` | local JSON draft, re-read on mtime change (`file` mode) |
| `--draft-id <id>` | Sleeper draft id to poll (`draft` mode); bare digits only |
| `POST /source` body | `{"picks": [...]}` inline, or `{"draft_id": "..."}`, plus optional `me`, `kind` |
| `data/draft-<id>.json` | durable saved draft; seeds the board on startup and replays offline |
| `data/bid-log-<id>.json` | append-only per-player bid ladder, grown from poll history |

| Output | Description |
| --- | --- |
| `GET /state.json` | the live board payload (see `03-rendering-contract.md`) |
| `GET /state.json?upto=n` | a frozen historical frame (see `04-time-travel-scrubber.md`) |
| `GET /config` | `draft_id`, `season`, `mode`, `kind`, `my_seat`, `seat_users` |
| `POST /source` | repoint the board at a new draft, no restart |
| `GET /health` | `ok` |
| `GET /bid-log.jsonl` | one NDJSON row per bid rung, denormalized with names/seats |
