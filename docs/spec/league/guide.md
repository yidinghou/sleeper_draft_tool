# The league model — reproduction guide

How to rebuild this module from scratch, in dependency order. Three files,
each depending only on the ones before it:

1. `python/vorp/league/config.py` — the frozen roster template and league
   constants. Depends on nothing.
2. `python/vorp/league/roster_fill.py` — the generic position-eligible
   bipartite matching engine. Depends on nothing (pure matching over its own
   dataclasses).
3. `python/vorp/league/teams.py` — the seats layer: the template applied to
   real teams holding real money and real slots. Depends on both files above.

Build them in this order and the tests for each layer will already have their
dependencies in place. There is no dedicated `test_config.py`,
`test_roster_fill.py`, or `test_teams.py` — every layer is pinned
**transitively** by the consumer suites named below.

## Step 1 — `python/vorp/league/config.py`

The frozen shape of the league. Nothing computes here; it is the one place the
raw Sleeper settings are read into a shared object. See
[01 · The roster template](01-roster-template.md).

Expose:

- `POSITIONS` — the tuple of positions in canonical display order
  (`"QB", "RB", "WR", "TE", "K", "DEF"`). Every list this module returns is
  ordered by this tuple, so build it first.
- `STREAMING_POSITIONS` — positions dropped from bench eligibility
  (`("DEF",)`). Used by the seats layer, not here.
- `FLEX_ELIGIBILITY: Dict[str, List[str]]` — which positions each flex type
  accepts (`FLEX` → RB/WR/TE, `REC_FLEX` → WR/TE, `SUPER_FLEX` → QB/RB/WR/TE).
- `LeagueConfig` — a `@dataclass(frozen=True)` holding `league_id`, `draft_id`,
  `season`, `teams`, `budget`, `min_bid`, `starting_slots` (concrete slots by
  position), `flex_slots` (counts by flex type), `bench_slots`, and an optional
  `plays_positions` override (default `None`). Methods:
  - `roster_size` (property) — concrete + flex + bench slot counts.
  - `flex_peers(position)` — every *other* position that competes for a flex
    slot, unioned across flex types.
  - `draftable_positions()` — positions with a concrete slot or accepted by a
    flex; returns `plays_positions` directly when set.
- `LEAGUE_CONFIG` — the one instance for the real 2026 draft
  (`teams=12`, `budget=200`, `min_bid=1`, `starting_slots={QB:1, RB:2, WR:2,
  TE:1, K:0, DEF:1}`, one each of `SUPER_FLEX`/`FLEX`/`REC_FLEX`,
  `bench_slots=6` → `roster_size == 16`).

> **Not yet built:** a division/identity layer (`Division`, `DIVISIONS`,
> `MY_USERNAME`, `MOCK_SEED`, `all_members()`, `division_index_for(...)`) is
> planned for `config.py` as board-labelling metadata for the live draft board
> (`../board/02-seat-identity-and-divisions.md`), independent of the VORP math
> below. It doesn't exist in `config.py` yet — the three layers in this guide
> don't need it.

## Step 2 — `python/vorp/league/roster_fill.py`

The generic engine: a points-maximizing assignment of players to
position-eligible slots. It knows nothing about seats, budgets, or replacement
level — it is handed a pool of players and a pool of slots and returns the
optimal fill. See [02 · Slot assignment](02-slot-assignment.md).

Expose:

- `RosterFillPlayer` — frozen dataclass `(player_id, position, points)`.
- `Slot` — frozen dataclass `(id, eligible_positions, seat_id=None)`. The
  matching ignores `seat_id` entirely; it exists only so a slot in a flat
  league-wide list can be traced back to its owner.
- `PositionFillSummary` — frozen dataclass `(reachable, level_points,
  selected_count, pool_exhausted=False)`.
- `assign_to_slots(players, slots) -> Dict[int, str]` — Kuhn's algorithm:
  players processed points-descending, each seated via an augmenting path that
  can reroute (never evict) an existing occupant. Returns `{slot_id: player_id}`
  for every filled slot.
- `solve_optimal_fill(players, slots) -> Set[str]` — `assign_to_slots` with the
  slot ids dropped, just the selected player set.
- `summarize_by_position(players, slots, selected_player_ids, positions)` — per
  position: `reachable` (does any slot accept it), `selected_count`,
  `level_points` (the best unselected player's points), and `pool_exhausted`
  (everyone at that position got seated, so `level_points` is `None`).

The private `_try_assign(...)` is the recursive augmenting-path helper; keep it
private.

## Step 3 — `python/vorp/league/teams.py`

The seats layer. Turns the per-team template into one `Slot` object per seat
per roster spot, so a single sale removes exactly one slot. See
[03 · Seats and sales](03-seats-and-sales.md).

Expose:

- `UNKNOWN_SEAT = -1` — the synthetic seat a sale lands on when the buyer is
  unknown.
- `Bought` — frozen dataclass `(player_id, position, amount)`.
- `Seat` — frozen dataclass `(seat_id, budget_left, bought=(), name=None)` with
  `spent()`. Note: the seat holds **budget and players, not the template**; the
  template lives once on `LeagueState.config`.
- `LeagueState` — frozen dataclass `(config, seats)`:
  - `opening(config)` (classmethod) — every seat full of money, empty of
    players.
  - `sell(player_id, position, amount, seat_id=None)` — returns a new state;
    nothing mutates. `seat_id=None` routes to `UNKNOWN_SEAT`.
  - `seat_slots(seat, bench, start_id=0)` — one seat's roster spots as `Slot`
    objects, expanding `FLEX_ELIGIBILITY` into each flex slot's
    `eligible_positions`. `bench=False` is starting slots only (what `01`/`08`
    fill); `bench=True` adds bench slots, whose eligibility is
    `draftable_positions()` minus `STREAMING_POSITIONS`. Public because
    `../vorp/08` values a player against one seat's starting slots.
  - `all_slots(bench)` — every seat's slots, flat; identical pre-draft to the
    old `count × teams` expansion.
  - `open_slots(bench)` — the league's remaining demand: slots no seat has
    filled, via the matching run per seat (`starting_slots()` /
    `full_roster_slots()` are the `bench=False` / `bench=True` wrappers).
  - `sold()`, `spent()`, `pool()` (`teams × budget − spent`), `spots_left()`.
  - `max_bid(seat_id)` — `budget_left − (open_count − 1) × min_bid`, i.e. a
    dollar reserved for every *other* open slot; `0` when the seat has no open
    slots, `None` when the seat id is unknown.

The private `_filled_slot_ids(...)` runs `assign_to_slots` over one seat with
all player points set to `0.0` (only the seated *count* matters for "which
slots are open"), keyed by slot id.

## Testing

Run, from the repo root:

```
python -m pytest python/tests/test_replacement_level.py python/tests/test_seat_value.py
```

(Equivalently, from `python/`: `python -m pytest tests/test_replacement_level.py
tests/test_seat_value.py`. The `pyproject.toml` sets `pythonpath = ["."]` so the
`vorp` package imports without an install.) Both suites should pass.

What each suite pins:

- **`test_replacement_level.py`** — the template + engine together, through
  `calculate_replacement_levels`. Pins flex contention (a strong TE class
  claims a shared FLEX/REC_FLEX slot from a weaker RB, and vice versa),
  replacement level as "the best player left outside the selected set" (the
  13th TE when 12 concrete TE slots exist and receivers claim every flex), and
  the `reachable=False` / `replacement_level=None` result for a position with
  no slot at all (K).
- **`test_seat_value.py`** — the seats layer + engine, through `seat_vorp` /
  `seat_bid`. Pins `seat_slots(bench=False)` matching (a back who reaches no
  open starting slot is worth 0; the same roster bought in reverse order values
  identically — the payoff for matching over a greedy rule), and the `max_bid`
  clamp exactly: an opening seat caps at `200 − 15×1 = 185`, a spent-down seat
  at `26`, a broke-but-not-full seat is "out" (bid `0`) rather than cheap, and
  `UNKNOWN_SEAT` has no values.

> A future `test_optimal_roster.py` (pinning `plan_roster` from the planned
> `09 · The best affordable roster` model) will join this list once that model
> is built — see `../vorp/09-optimal-roster.md`.

## Gotchas

- **Flex eligibility is baked into the slot, not the engine.** `assign_to_slots`
  only checks `position in slot.eligible_positions`; it has no concept of a
  "flex type." `seat_slots` is where `FLEX_ELIGIBILITY[flex]` is expanded into a
  slot's eligible tuple, so a `SUPER_FLEX` slot literally carries
  `("QB","RB","WR","TE")`. Get this expansion wrong and the matching silently
  under- or over-fills.
- **Slot ids must be globally unique across seats.** The matching keys its
  `visited` and `occupant` sets by `slot.id`. `all_slots` / `open_slots`
  therefore advance `next_id` by *every* slot generated for a seat, not just the
  ones that survive the open-slot filter — reusing ids across seats corrupts the
  match.
- **`max_bid` reserves a dollar per *other* open slot.** The formula is
  `budget_left − (open_count − 1) × min_bid`, so max bid falls faster than
  budget as a seat fills up. `open_count == 0` returns `0` (nowhere to put a
  player), and an unknown seat id returns `None`.
- **`UNKNOWN_SEAT` is an accounting device, not a 13th team.** It owns no
  template and contributes no demand, so it is skipped in `all_slots` /
  `open_slots`. Its budget is allowed to go negative on the first unattributed
  sale so the league `pool()` still nets to the money actually left in the room
  — but that seat's own `budget_left` and `max_bid` are fiction, and so are the
  readouts of whichever real seat truly bought the player.
- **`pool_exhausted` is not a bar of 0.** `summarize_by_position` distinguishes
  "no slot accepts this position" (`reachable=False`, `level_points=None`) from
  "every player at this position got seated because the pool ran out"
  (`pool_exhausted=True`, `level_points=None`). Callers must not read either as
  a replacement level of 0.
- **`_filled_slot_ids` sets points to 0.0 on purpose.** Which of a seat's slots
  are occupied depends only on the *count* and positions of what it bought, not
  on how good the players are — so the per-seat fill runs at uniform points and
  is order-independent.
