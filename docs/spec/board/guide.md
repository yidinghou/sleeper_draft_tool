# The live draft board — reproduction guide — WIP

> **Work in progress.** The pricing core and league model this server would
> sit on are both built (see `../vorp/guide.md` and `../league/guide.md`).
> None of the six layers below exist yet; see the [module index](index.md)
> for status. This guide describes the intended build order for when work
> starts.

How to rebuild the live draft board from scratch, in dependency order. It is one
server process (`python/scripts/draft_board.py`) on top of the pricing core and
league model — build those first (see `../vorp/guide.md` and `../league/guide.md`),
then add the six layers below in order. Each depends only on the ones before it.

1. **Sleeper client** — the read-only draft reads. Depends on nothing but stdlib.
2. **Server skeleton + `/state.json`** — the HTTP surface and `build_payload`.
3. **Source modes + polling** — file re-read, Sleeper poll, inline paste.
4. **Seat identity + divisions** — who sits where, and how they group.
5. **The slide template** — the deck that renders the payload.
6. **Scrubber + frame cache** — historical frames, memoized on disk.

## Step 1 — `python/vorp/sleeper_client.py`

The Python half of `src/sleeper.ts`, name-for-name, so the pricing process needs
no second language runtime. See [01 · Live data ingestion](01-live-data-ingestion.md).
Expose:

- `fetch_draft(draft_id)`, `fetch_draft_picks(draft_id)`,
  `fetch_league_users(league_id)` — the three GETs, all through a private `_get`
  that appends `?_cb=<epoch_ms>` to defeat Sleeper's CDN cache.
- `draft_fingerprint(draft)` — the cheap-poll signature:
  `status | nominated_player_id | highest_offer | offering_slot | last_action_at`.
- `parse_nomination(draft) -> Nomination` — the on-block player + current high bid.
- `seat_identity(draft, users, raw_picks=None)` — `{seat_id: {user_id, username,
  display_name}}`, joining `draft_order` (both dict and array shapes) and each
  pick's `picked_by`.

## Step 2 — the server skeleton + `build_payload`

The `Board` class holds the config, the loaded projections, and one live
`payload` under a lock; `make_handler` wires the routes. Build `build_payload`
first — it is the whole contract (see
[03 · The rendering contract](03-rendering-contract.md)): run `price_board` on
the residual `LeagueState`, then assemble `seats`, `divisions`, `state_table`,
`matrix`, `block`, `my_plan`, `players`, `log`, and the residual-state scalars
(`pool`, `spent`, `vorp_rate`, `paid_rate`, `starting_slots_left`). Routes:
`GET /` (landing), `GET /board` (the deck), `GET /state.json` (+`?upto=`),
`GET /config`, `GET /health`, `GET /bid-log.jsonl`, `POST /source`.

## Step 3 — the three source modes + polling

`build_state` replays picks into a residual `LeagueState` (a pick with no
`draft_slot` lands on `UNKNOWN_SEAT`). Then:

- **`file`** — `refresh_from_file` re-reads `--picks-file` on mtime change.
- **`draft`** — the `poller` thread runs `poll_sleeper_once`: cheap `/draft`
  poll, and only on a `draft_fingerprint` change does it refetch `/picks`,
  append to `data/bid-log-<id>.json` (`_append_bid_log`), and save
  `data/draft-<id>.json` (`_save_draft`). `load_saved_draft` seeds from that file
  on startup so the board works even offline.
- **`inline`** — `set_source` holds pasted picks; it also validates a pasted
  draft id down to bare digits.

Cadence is adaptive: `--poll 0.75` idle, `--poll-live 0.2` while a player is on
the block.

## Step 4 — seat identity + divisions

See [02 · Seat identity and divisions](02-seat-identity-and-divisions.md).
`random_fill` composes real pins + a `MOCK_SEED`-shuffled member pool into all
twelve seats; `refresh_seat_identity` overwrites placeholders as the draft seeds;
`resolve_my_seat` finds `MY_USERNAME`; `build_divisions` groups seats mine-first
and returns the `seat_order` permutation.

## Step 5 — the slide template

`templates/board_slides.html` (deck) and `templates/board_landing.html` (source
picker). The deck holds no model — `renderAll` fans `/state.json` out to
`renderHeader`, `renderPower`, `renderStateTable`, `renderMatrix`,
`renderRosters`, etc., and polls at the same adaptive cadence. The one piece of
logic it does own, `fillSlots`, is a tested mirror of
`../league/02-slot-assignment.md`'s bipartite matching. Visual system: the golden
POC `poc/board-slides-golden-new.html`.

## Step 6 — the scrubber + frame cache

See [04 · The time-travel scrubber](04-time-travel-scrubber.md).
`get_payload_upto(n)` replays the first `n` picks through `build_payload`;
`_prefix_sig` keys the memo on `FRAME_SCHEMA_VERSION` + the picks prefix + seat
names; `_load_frame`/`_store_frame` back it with `data/frames-<id>/<n>.json`.
The `frame_warmer` thread and `start_prewarm` keep frames warm; the client's
`scrubTo`/`fetchFrame` coalesce fetches while dragging.

## Running it

From the `python/` directory:

```
# Replay a local mock (the testable path), your seat is 3:
python scripts/draft_board.py --picks-file tests/fixtures/mock-draft.json --me 3

# Poll a live/mock Sleeper draft (defaults to this league's draft id):
python scripts/draft_board.py --draft-id 1372724723120631808

# No flags: poll the configured league draft:
python scripts/draft_board.py

# Bootstrap the division config — print seat/name/username and exit:
python scripts/draft_board.py --draft-id 1372724723120631808 --print-seats
```

Then open `http://127.0.0.1:8770/` (landing → pick a source), `/board` (the
deck), or `/state.json` (the raw payload). Flags: `--me` (1-indexed fallback
seat), `--port` (default `8770`), `--w-floor` (default `1.0`, pure VORP),
`--matrix-top` (default `300`), `--season`, `--poll`/`--poll-live`.

## Testing

Run, from the repo root:

```
python -m pytest python/tests/test_draft_board.py
```

(Equivalently `cd python && python -m pytest tests/test_draft_board.py`; the
`pyproject.toml` sets `pythonpath = ["."]` so `vorp`/`scripts` import without an
install.) 35 tests at time of writing, all passing.

What the fixtures pin:

- **`tests/fixtures/mock-draft.json`** — the primary fixture: 14 picks (summing
  to `$602`), a nomination (Trey McBride, TE, `$14`, held by seat 9), explicit
  `seat_names`, and a `bid_log`. It drives the reconciliation, header, matrix,
  division, and scrubber tests. Because it carries no real Sleeper identity, it
  also exercises the mock-mode auto-split into three divisions of four.
- **`tests/fixtures/live-draft-snapshot.json`** — a saved-draft *envelope*
  (`data/draft-<id>.json` shape): 27 picks, `kind: "mock"`, `seat_users`, a
  live `nomination`, and a whole `bid_book`. It pins that the saved envelope
  replays as a picks file and rehydrates its bid book offline. (It is also the
  frozen snapshot `test_optimal_roster.py` plans against.)

## Gotchas

- **The bid ladder is append-only and only as complete as the polling saw.**
  `_append_bid_log` appends a rung to `data/bid-log-<id>.json` only when it
  differs from the last recorded one, and Sleeper exposes just the current high
  bid — so rungs raised and outbid between two polls are never captured. The
  slide-1 timeline is a sample of the bidding, not a transcript.
- **Bumping `FRAME_SCHEMA_VERSION` invalidates every persisted frame.** It is
  folded into `_prefix_sig`, so any change to the payload shape must bump it
  (currently `8`) or the scrubber will serve stale `data/frames-<id>/<n>.json`
  frames the current renderer can't read. Bumping it is the invalidation — no
  manual purge needed.
- **Every Sleeper read must be cache-busted.** `_get` appends `?_cb=<epoch_ms>`;
  without it Sleeper's CDN can serve `/draft` responses stale by hours during a
  live auction, and the board silently freezes on old bids.
- **`MOCK_SEED` determinism is load-bearing for tests and screenshots.** The
  open-seat fill is `random.Random(MOCK_SEED)`, never the wall clock, so a given
  mock lays out identically every run. A test asserting a specific seat's name
  or `my_division` (e.g. `test_mock_without_names_gets_random_real_members`)
  breaks if the seed or the member list changes.
- **A pick with no `draft_slot` lands on `UNKNOWN_SEAT`, not seat 0.**
  `build_state` routes an unattributed manual pick to the synthetic seat so the
  pool still reconciles without charging a real seat — the sale leaves the pool,
  but no seat's roster or `max_bid` is touched.
- **Prewarm stays off until the server enables it.** `_prewarm_enabled` is set
  in `main`, not the constructor, so programmatic/unit use of `Board` doesn't
  spawn full-draft reprice storms on every `_apply`.
