# 04 · The time-travel scrubber (FAQ)

### What does this compute?

The board as it stood after any pick `n`, so you can scrub backward through a
draft and watch the prices move. `get_payload_upto(n)` replays only the first
`n` picks through the same build path as the live board and returns a frozen
frame; a pinned scrubber UI drives it. Every frame is memoized in memory and on
disk, so revisiting a moment is instant.

### Why not just re-solve the board on every slider move?

Because a full reprice is roughly a 1.5-second `price_board` solve, and a scrub
drags across dozens of picks in a second. Re-solving live on every step would
make the slider unusable, and — worse — a fast drag fires dozens of concurrent
`/state.json?upto=` requests that would thrash the GIL with parallel reprices.
Memoization plus a build lock turns the whole draft into a set of frames each
built at most once, ever.

### How does it actually work?

A frame depends only on the first `n` picks (a scrubbed view has no live
nomination), so it stays valid as the draft grows — the draft is append-only.
The cache key is a **prefix signature** (`_prefix_sig`): a JSON blob of the
schema version, the first `n` picks as `[pick_no, player_id, amount]` triples,
and the seat names the build bakes into each roster.

```
sig = {"v": FRAME_SCHEMA_VERSION, "picks": [[pick_no, pid, amt], ...][:n],
       "names": seat_names}   # json.dumps(..., sort_keys=True)
```

`FRAME_SCHEMA_VERSION` is **8**. Anything that would change the rendered board
changes the sig, so a stale entry misses and rebuilds; bumping the version
invalidates every persisted frame at once (its history is in the constant's
docstring — v8 added `paid_rate`, `min_bid`, `starting_slots_left`).

`_load_frame`/`_store_frame` back the in-memory `_frame_cache` with a disk cache
at `data/frames-<id>/<n>.json` (keyed on the draft id, or the picks-file stem;
`None` for an inline paste, which has no stable id). `get_payload_upto` reads the
cache, and on a miss takes `_build_lock`, double-checks the cache (a concurrent
scrub may have just built it), builds once, and stores. The per-request fields
that must not be frozen — `my_seat`, `view`, the just-sold `block`, and its bid
ladder — are re-stamped onto a shallow copy after the cached body is fetched.

Two background threads keep frames warm: `start_prewarm` (fired on every pick
change when the server enables it) builds every frame `1..total` under a
generation counter that cancels a stale warmer, and `frame_warmer` builds the
newest cold frame first (the likeliest scrub target). On the client, `scrubTo`
sets `viewPick` synchronously so rapid keys accumulate instead of racing;
a `frameCache` and a `scrubToken` coalesce in-flight fetches so only the pick the
drag lands on is requested, and only the latest response paints.

### What's the output, precisely?

The same payload shape as live (`03-rendering-contract.md`), with three
differences: `view` is `{pick: n, total, live: false}`; there is no live
nomination, so `block` instead surfaces the pick that just **sold** at `n`
(`sold_block` — winner, sale price, buyer, with `sold: true` so the client
relabels to "Just sold"); and `bid_ladder` carries that player's recorded
ladder. `get_payload_upto` never mutates the cached live payload.

### What does that look like in practice?

- **Scrub to the opening bell:** `upto(0)` returns the pre-draft board —
  `log == []`, `spent == 0`, `block == null`.
- **Past the end clamps:** `upto(999)` clamps to the full draft (`view.pick`
  becomes `total`); the client's `scrubTo` treats `n > total` as a snap back to
  live.
- **Worked example:** on the mock fixture, `get_payload_upto(3)` returns
  `view == {"pick": 3, "total": 14, "live": false}`, `spent == 169`
  (`61 + 58 + 50`, the first three picks), and a `block` showing **Josh Allen**
  as just-sold — exactly `test_get_payload_upto_replays_only_the_first_n_picks`
  and `test_get_payload_upto_block_is_the_pick_that_just_sold`. Fetch it twice
  and `build_payload` runs once (`test_get_payload_upto_is_memoized`).

### What drives the scrubber from the keyboard?

The pinned scrub bar mirrors to `Shift+←` / `Shift+→` (step one pick, guarded so
the plain-arrow slide navigation doesn't also fire) and `Esc` (snap back to
live). Holding `T` shows a dotted-outline wireframe peek of the region layout —
`body.peek-wire`, released on keyup or window blur. These are UI conveniences on
top of the same `scrubTo`/`goLive` the slider calls.

### What about a frame from before a schema change?

It misses. Its persisted `sig` still carries the old `v`, so `_load_frame`'s
`sig` comparison fails and the frame rebuilds against the current schema rather
than serving a payload the current renderer can't read. That's the whole point
of folding `FRAME_SCHEMA_VERSION` into the signature — a bump is a cache
invalidation, not a manual purge.

### What's the catch?

A frame is only reconstructable from the picks that were saved. It replays the
sale record, but Sleeper never exposes past nominations, so the scrubbed
"on the block" is the pick's **winner** shown as sold — never the live bidding
that actually happened at that moment. The bid timeline for a historical frame
is only as complete as the ladder that was recorded live into
`data/bid-log-<id>.json` (`01-live-data-ingestion.md`'s catch); on an offline
replay it comes from the bid book rehydrated from the saved envelope, or is
empty if none was captured.

### Does a fast scrub break anything server-side?

No. Superseded `/state.json?upto=` requests are aborted by the client mid-drag,
and `QuietThreadingHTTPServer` swallows the resulting `BrokenPipeError` /
`ConnectionResetError` so they don't spam the console — a hung-up client is
nothing broken on the server's side.

---

## Reference

**Depends on:** `build_payload`/`price_board` for the frame body
(`03-rendering-contract.md`, `../vorp/07-live-draft-board.md`); the picks and
seat names persisted by ingestion (`01-live-data-ingestion.md`).
**Implemented in:** `python/scripts/draft_board.py` — `get_payload_upto`,
`_prefix_sig`, `_load_frame`/`_store_frame`, `_frame_store_dir`,
`FRAME_SCHEMA_VERSION`, `sold_block`, `start_prewarm`/`warm_next_cold_frame`, and
the `frame_warmer` thread; scrubber UI (`scrubTo`, `fetchFrame`, `goLive`,
`warmFrames`, the keydown handlers) in
`python/scripts/templates/board_slides.html`. **Done when:** `upto(n)` replays
exactly the first `n` picks, is built at most once per prefix, surfaces the
just-sold pick as `block`, clamps out of range, and never mutates the live
payload — see `test_get_payload_upto_replays_only_the_first_n_picks`,
`test_get_payload_upto_is_memoized`,
`test_get_payload_upto_block_is_the_pick_that_just_sold`, and
`test_get_payload_upto_clamps_and_leaves_live_payload_untouched`.

| Input | Description |
| --- | --- |
| `n` | 1-indexed pick to freeze at; `0` = opening board, clamped to `total` |
| picks prefix | first `n` picks (by `pick_no`), replayed into a residual state |
| `seat_names` | baked into the frame's rosters; part of the cache signature |
| `FRAME_SCHEMA_VERSION` | `8`; folded into the sig so a bump invalidates the cache |

| Output | Description |
| --- | --- |
| frozen payload | live-shaped, with `view.live == false` and `view.pick == n` |
| `block` | the pick that sold at `n` (`sold: true`), or `null` at `n == 0` |
| `bid_ladder` | that player's recorded ladder (live file or rehydrated book) |
| `data/frames-<id>/<n>.json` | persisted frame, survives restart, keyed by prefix sig |
