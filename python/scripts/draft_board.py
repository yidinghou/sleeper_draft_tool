#!/usr/bin/env python3
"""The live draft board server -- see docs/spec/board/index.md.

Steps 2, 3, 4, and 6 of docs/spec/board/guide.md's build order: the server
skeleton, `/state.json`, Sleeper polling, seat identity + divisions, the
per-seat bid matrix, `my_plan`, `block`, and the time-travel scrubber
(`get_payload_upto`, disk-persisted frames). This is still a partial slice
of the full rendering contract (docs/spec/board/03-rendering-contract.md):
`block`'s `market`/`wk3VorpD` fields aren't wired in (no market-price or
weeks-1-3 data source is loaded here -- see `block_info`'s docstring), and
no payload anywhere carries a player's *name* -- `RosterFillPlayer` doesn't
carry one, so the deck (below) renders raw player ids until that's threaded
through.

Step 5, the slide deck, is in progress: `templates/board_slides.html` exists
and serves at `GET /board` (and `GET /` -- there's no separate landing/
source-picker page yet, both routes serve the same deck). So far it has the
header (on-block hero, per-seat worth) and the buying-power bars; the
draft-state table, pool matrix, roster cards, and the live poll loop are
still placeholder cards in the template.

Two source modes: `--picks-file <path>` (`file` mode, re-read on mtime
change -- a hand-edited nomination key is the only source of a live block
there, since there's no spec-given format for a manual entry pane's
nomination, only Sleeper's own `metadata`; this repo invented
`{player_id, highest_offer, offering_slot}`), or `--draft-id <id>` (`draft`
mode, the default when `--picks-file` is omitted): a background `poller`
thread drives `Board.poll_sleeper_once` at an adaptive cadence
(`--poll`/`--poll-live`), durably saving the draft and appending to the bid
ladder on every real change -- see `01-live-data-ingestion.md`.

The matrix has no cache in front of it (that's guide.md step 6, not built),
so it runs one lineup solve per `(player, real seat)` pair on every
`/state.json` request -- `--matrix-top` (default 300) bounds it.

Usage: python scripts/draft_board.py --picks-file <path> [--me 3] [--port 8770]
                                     [--season 2026] [--w-floor 1.0]
                                     [--matrix-top 300]
       python scripts/draft_board.py --draft-id <id> [--poll 0.75] [--poll-live 0.2]
       python scripts/draft_board.py --draft-id <id> --print-seats
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.board import price_board  # noqa: E402
from vorp.csv_loader import REPO_ROOT, load_players_from_csv, projections_csv_path  # noqa: E402
from vorp.league.config import (  # noqa: E402
    DIVISIONS,
    LEAGUE_CONFIG,
    MOCK_SEED,
    MY_USERNAME,
    LeagueConfig,
    all_members,
    division_index_for,
)
from vorp.league.roster_fill import RosterFillPlayer as Player  # noqa: E402
from vorp.league.teams import UNKNOWN_SEAT, LeagueState  # noqa: E402
from vorp.optimal_roster import RosterPlan, Target, plan_roster  # noqa: E402
from vorp.seat_value import price_from_value, seat_values  # noqa: E402
from vorp.sleeper_client import (  # noqa: E402
    draft_fingerprint,
    fetch_draft,
    fetch_draft_picks,
    fetch_league_users,
    parse_nomination,
    seat_identity,
)

DEFAULT_PORT = 8770
DEFAULT_W_FLOOR = 1.0
DEFAULT_MATRIX_TOP = 300


def build_state(picks: List[Dict[str, Any]], config: LeagueConfig) -> LeagueState:
    """Replay a picks list into a residual `LeagueState`.

    Each pick is `{player_id, amount, position, draft_slot}`.  `draft_slot` is
    Sleeper's 1-indexed seat number; `LeagueState` seats are 0-indexed, so it
    is shifted by one.  A pick with no `draft_slot` -- a manual entry with no
    recorded buyer -- lands on the synthetic `UNKNOWN_SEAT` rather than seat
    0, so the pool still reconciles without charging a real seat.
    """
    state = LeagueState.opening(config)
    for pick in picks:
        draft_slot = pick.get("draft_slot")
        seat_id = int(draft_slot) - 1 if draft_slot is not None else None
        state = state.sell(
            str(pick["player_id"]),
            pick["position"],
            int(pick["amount"]),
            seat_id=seat_id,
        )
    return state


def seat_matrix(
    state: LeagueState,
    remaining: List[Player],
    players: List[Player],
    board: Dict[str, Any],
    matrix_top: int = DEFAULT_MATRIX_TOP,
    force_ids: Tuple[str, ...] = (),
) -> List[Dict[str, Any]]:
    """Per-seat bid matrix -- see docs/spec/board/03-rendering-contract.md.

    Every priced player as a row, capped to the top `matrix_top` by board
    price plus any `force_ids` (the on-block player is meant to always be
    forced in, so his per-seat worth exists even off the top of the board --
    wiring that in is follow-up work, once a nomination source exists). Each
    row carries a bid per real seat (`UNKNOWN_SEAT` owns no roster and gets
    none), the likely winner (highest bid), the price-setter (2nd-highest),
    and the expected winning price (price-setter + $1, or the board price
    when nobody but the winner would bid at all).

    Runs one lineup solve per `(row, real seat)` pair -- the reason for the
    cap. There is no caching in front of this yet (the frame cache is
    guide.md step 6, not built), so a live server should keep `matrix_top`
    modest; the shipped default (300) is effectively "the whole board"
    pre-draft (~192 players).
    """
    real_seats = [s.seat_id for s in state.seats if s.seat_id != UNKNOWN_SEAT]
    prices = board["rows"]
    ranked = sorted(prices, key=lambda pid: -prices[pid]["price"])
    top_ids = list(dict.fromkeys(ranked[:matrix_top] + list(force_ids)))
    top_ids = [pid for pid in top_ids if pid in prices]

    replacement = {pos: level["replacement"] for pos, level in board["levels"].items()}
    points_by_id = {p.player_id: p.points for p in players}
    by_id = {p.player_id: p for p in remaining}
    rate = board["vorp_rate"]

    bids_by_seat: Dict[int, Dict[str, int]] = {}
    for seat_id in real_seats:
        candidates = [by_id[pid] for pid in top_ids if pid in by_id]
        values = seat_values(state, seat_id, candidates, replacement, points_by_id)
        bids_by_seat[seat_id] = {
            pid: price_from_value(values.get(pid, 0.0), rate, state, seat_id)
            for pid in top_ids
        }

    rows = []
    for pid in top_ids:
        bids = {seat_id: bids_by_seat[seat_id][pid] for seat_id in real_seats}
        ranked_bids = sorted(bids.items(), key=lambda kv: -kv[1])
        winner_seat, winner_bid = ranked_bids[0] if ranked_bids else (None, 0)
        setter_bid = ranked_bids[1][1] if len(ranked_bids) > 1 else 0
        rows.append(
            {
                "player_id": pid,
                "price": prices[pid]["price"],
                "bids": bids,
                "winner": winner_seat if winner_bid > 0 else None,
                "price_setter_bid": setter_bid,
                "expected_price": (setter_bid + 1) if setter_bid > 0 else prices[pid]["price"],
            }
        )
    return rows


def _target_dict(t: Target) -> Dict[str, Any]:
    return {
        "player_id": t.player_id,
        "position": t.position,
        "price": t.price,
        "points_gain": round(t.points_gain, 1),
        "kind": t.kind,
    }


def block_info(
    nomination: Optional[Dict[str, Any]],
    remaining: List[Player],
    board: Dict[str, Any],
    matrix_rows: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """The on-block player folded with board price, VORP $/VOLR $, the
    current high bid, and a per-seat worth row -- see
    docs/spec/board/03-rendering-contract.md. `None` when nothing is on the
    block (`nomination` is falsy, or names a player already sold or unpriced
    -- the header degrades to "nobody on the block").

    Only `price`/`vorp_dollar`/`volr_dollar` are wired in here -- the full
    contract's `market` (Sleeper's own dollar) and `wk3VorpD` (weeks-1-3
    pricing) need data sources (the boberto CSV, the `wk1_3` points column)
    this server doesn't load. `bids` comes from `matrix_rows`, where the
    caller is expected to have forced this player's id into the matrix solve
    even if he's off the top of the board (`seat_matrix`'s `force_ids`) --
    his per-seat worth should exist regardless of his price rank.
    """
    if not nomination:
        return None
    pid = nomination.get("player_id")
    row = board["rows"].get(pid) if pid else None
    if not pid or row is None:
        return None
    player = next((p for p in remaining if p.player_id == pid), None)
    matrix_row = next((r for r in matrix_rows if r["player_id"] == pid), None)
    return {
        "player_id": pid,
        "position": player.position if player else None,
        "points": round(player.points, 1) if player else None,
        "price": row["price"],
        "vorp_dollar": row["vorp_dollar"],
        "volr_dollar": row["volr_dollar"],
        "highest_offer": nomination.get("highest_offer"),
        "offering_slot": nomination.get("offering_slot"),
        "bids": matrix_row["bids"] if matrix_row else {},
    }


def plan_payload(plan: RosterPlan) -> Dict[str, Any]:
    """`RosterPlan` as a JSON-serializable dict -- the `my_plan` payload key."""
    return {
        "targets": [_target_dict(t) for t in plan.targets],
        "fills": [_target_dict(f) for f in plan.fills],
        "spend": plan.spend,
        "reserve": plan.reserve,
        "budget_left_after": plan.budget_left_after,
        "points_before": round(plan.points_before, 1),
        "points_after": round(plan.points_after, 1),
        "points_gain": round(plan.points_gain, 1),
        "lineup_ids": list(plan.lineup_ids),
        "open_slots_after": plan.open_slots_after,
    }


def _seat_summaries(state: LeagueState) -> List[Dict[str, Any]]:
    """Every real seat's roster summary -- what the deck's Rosters slide
    needs to run `fillSlots` against. `UNKNOWN_SEAT` is excluded; it owns no
    roster. Doesn't include each pick's opening price (the full contract's
    `lines[].price`, for over/under-pay tags) -- that needs a second
    `price_board` solve against the opening board, not wired in here.
    """
    return [
        {
            "seat_id": seat.seat_id,
            "budget_left": seat.budget_left,
            "max_bid": state.max_bid(seat.seat_id),
            "bought": [
                {"player_id": b.player_id, "position": b.position, "amount": b.amount}
                for b in seat.bought
            ],
        }
        for seat in state.seats
        if seat.seat_id != UNKNOWN_SEAT
    ]


def build_payload(
    state: LeagueState,
    players: List[Player],
    config: LeagueConfig,
    w_floor: float,
    *,
    seat_users: Optional[Dict[int, Dict[str, Any]]] = None,
    divisions: Optional[List[Dict[str, Any]]] = None,
    seat_order: Optional[List[int]] = None,
    my_seat: Optional[int] = None,
    my_division: Optional[int] = None,
    matrix_top: int = DEFAULT_MATRIX_TOP,
    nomination: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The (still partial) `/state.json` payload -- see
    docs/spec/board/03-rendering-contract.md. The identity-derived keys
    (`seat_users`, `divisions`, `seat_order`, `my_seat`, `my_division`) and
    `my_plan` are included only when `my_seat` is supplied (and resolves to a
    real seat), so this stays a pure function callable without an identity
    source. `my_plan` runs `09`'s `plan_roster` with `fill_all=True` -- a
    live board wants the whole completed roster, not just the value-adding
    buys, with fills clearly tagged (`kind="fill"`) so they never masquerade
    as lineup upgrades. `block` is `None` unless `nomination` names a real,
    still-unsold, priced player -- see `block_info`. `seats` is every real
    seat's roster summary (`_seat_summaries`) -- always included, no
    identity source needed.
    """
    sold_ids = set(state.sold())
    remaining = [p for p in players if p.player_id not in sold_ids]
    by_id = {p.player_id: p for p in remaining}
    board = price_board(state, remaining, config, w_floor)

    block_pid = nomination.get("player_id") if nomination else None
    force_ids = (block_pid,) if block_pid else ()
    matrix = seat_matrix(state, remaining, players, board, matrix_top=matrix_top, force_ids=force_ids)

    payload: Dict[str, Any] = {
        "pool": board["pool"],
        "spent": config.teams * config.budget - board["pool"],
        "spots_left": board["spots_left"],
        "vorp_rate": board["vorp_rate"],
        "levels": board["levels"],
        "players": [
            {
                "player_id": pid,
                "position": by_id[pid].position,
                "points": round(by_id[pid].points, 1),
                **row,
            }
            for pid, row in board["rows"].items()
        ],
        "matrix": matrix,
        "block": block_info(nomination, remaining, board, matrix),
        "seats": _seat_summaries(state),
    }
    if seat_users is not None:
        payload["seat_users"] = seat_users
    if divisions is not None:
        payload["divisions"] = divisions
    if seat_order is not None:
        payload["seat_order"] = seat_order
    if my_seat is not None:
        payload["my_seat"] = my_seat
    if my_division is not None:
        payload["my_division"] = my_division
    if my_seat is not None and my_seat != UNKNOWN_SEAT:
        prices = {pid: row["price"] for pid, row in board["rows"].items()}
        replacement = {pos: level["replacement"] for pos, level in board["levels"].items()}
        plan = plan_roster(state, my_seat, remaining, prices, replacement, fill_all=True)
        payload["my_plan"] = plan_payload(plan)
    return payload


# --------------------------------------------------------------------------
# Seat identity and divisions -- see
# docs/spec/board/02-seat-identity-and-divisions.md.
# --------------------------------------------------------------------------


def random_fill(
    pins: Dict[int, Dict[str, Any]], config: LeagueConfig
) -> Dict[int, Dict[str, Any]]:
    """Compose real seat pins with a `MOCK_SEED`-shuffled fill of every other
    seat, so all `config.teams` seats always have a plausible manager.

    Real pins are kept exactly. Every other seat draws a league member from
    `all_members()`, shuffled deterministically; members already sitting in a
    real pin are dropped from the pool first, so nobody appears twice.
    """
    pinned = {
        (identity.get("username") or identity.get("display_name") or "").lower()
        for identity in pins.values()
    }
    pool = [member for member in all_members() if member.lower() not in pinned]
    random.Random(MOCK_SEED).shuffle(pool)

    identity: Dict[int, Dict[str, Any]] = dict(pins)
    pool_iter = iter(pool)
    for seat_id in range(config.teams):
        if seat_id in identity:
            continue
        member = next(pool_iter, f"seat-{seat_id + 1}")
        identity[seat_id] = {"user_id": None, "username": member, "display_name": member}
    return identity


def refresh_seat_identity(
    draft: Dict[str, Any],
    users: List[Dict[str, Any]],
    raw_picks: Optional[List[Dict[str, Any]]],
    config: LeagueConfig,
) -> Dict[int, Dict[str, Any]]:
    """The full `seat_users` map: real pins from the draft, filled out to
    every seat by `random_fill`. A pin's `user_id` is never `None` (it comes
    straight from Sleeper); a `random_fill` placeholder always has
    `user_id: None`, which is how `build_divisions` tells a fully-seeded
    league apart from a mock/partial one.
    """
    pins = seat_identity(draft, users, raw_picks)
    return random_fill(pins, config)


def resolve_my_seat(seat_users: Dict[int, Dict[str, Any]], me_fallback: Optional[int]) -> int:
    """The 0-indexed seat whose identity matches `MY_USERNAME`,
    case-insensitive against either `username` or `display_name` (Sleeper
    often leaves one blank). Falls back to `me_fallback` (1-indexed `--me`)
    when the handle isn't present in any *real* seat yet.

    Only a real pin (`user_id` set) counts as a match. `MY_USERNAME` is
    itself one of `all_members()` (it has to be, for "my division" to ever
    resolve), so it can just as easily land as one of `random_fill`'s
    synthetic placeholders -- a coincidence, not a real seat -- which would
    otherwise silently override `--me` on a mock draft.
    """
    needle = MY_USERNAME.lower()
    for seat_id, identity in seat_users.items():
        if identity.get("user_id") is None:
            continue
        username = (identity.get("username") or "").lower()
        display_name = (identity.get("display_name") or "").lower()
        if needle and needle in (username, display_name):
            return seat_id
    return (me_fallback - 1) if me_fallback is not None else 0


def build_divisions(
    seat_users: Dict[int, Dict[str, Any]], config: LeagueConfig, my_seat: int
) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Group seats into `DIVISIONS` bands, my division first, then the rest
    in config order, then a trailing "Unassigned" band for any seat that
    matches no division. Returns `(divisions, seat_order)` -- `seat_order` is
    a strict permutation of the seat ids for column reordering; the per-seat
    `bids` arrays stay seat-indexed regardless of display order.

    A fully-seeded league (every seat has a real `user_id`, i.e. no
    `random_fill` placeholders left) groups by the config's username ->
    division map. Otherwise (mock, or a real draft still filling in) it falls
    back to an even auto-split by seat order, so the bands still render
    before real identity exists.
    """
    n = config.teams
    num_divisions = len(DIVISIONS)
    fully_seeded = all(
        seat_users.get(seat_id, {}).get("user_id") is not None for seat_id in range(n)
    )

    assignment: Dict[int, Optional[int]] = {}
    if fully_seeded:
        for seat_id in range(n):
            identity = seat_users[seat_id]
            assignment[seat_id] = division_index_for(
                identity.get("username") or identity.get("display_name")
            )
    else:
        per_division = -(-n // num_divisions)  # ceil
        for seat_id in range(n):
            assignment[seat_id] = min(seat_id // per_division, num_divisions - 1)

    my_division = assignment.get(my_seat)
    if my_division is None:
        my_division = 0

    bands: List[Dict[str, Any]] = []
    for div_idx in sorted(range(num_divisions), key=lambda i: (i != my_division, i)):
        seats = sorted(sid for sid, d in assignment.items() if d == div_idx)
        if seats:
            bands.append(
                {
                    "name": DIVISIONS[div_idx].name,
                    "index": div_idx,
                    "mine": div_idx == my_division,
                    "seats": seats,
                }
            )

    unassigned = sorted(sid for sid, d in assignment.items() if d is None)
    if unassigned:
        bands.append({"name": "Unassigned", "index": num_divisions, "mine": False, "seats": unassigned})

    seat_order = [sid for band in bands for sid in band["seats"]]
    return bands, seat_order


def print_seats(draft: Dict[str, Any], users: List[Dict[str, Any]]) -> None:
    """Read-only bootstrap helper: print each seat's real 1-indexed slot,
    `display_name`, and `username`, then exit. Copy the usernames into
    `DIVISIONS` in `python/vorp/league/config.py`.
    """
    identity = seat_identity(draft, users, raw_picks=None)
    for seat_id in sorted(identity):
        entry = identity[seat_id]
        print(f"seat {seat_id + 1}: {entry.get('display_name')} ({entry.get('username')})")


def _pick_from_sleeper(raw: Dict[str, Any]) -> Dict[str, Any]:
    """A Sleeper `DraftPick` (see `src/sleeper.ts`) as the internal pick
    shape `build_state` reads. `metadata.amount` is the real sold price --
    the auction dollar Sleeper can only be scraped for elsewhere, but a
    completed pick's own record carries it directly.
    """
    meta = raw.get("metadata") or {}
    return {
        "player_id": str(raw.get("player_id") or meta.get("player_id")),
        "position": meta.get("position"),
        "amount": int(meta.get("amount") or 0),
        "draft_slot": raw.get("draft_slot"),
    }


def _nomination_from_sleeper(draft: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """`sleeper_client.parse_nomination`'s `Nomination` as the internal
    nomination dict `block_info` reads. `None` when nothing is on the block.
    """
    nomination = parse_nomination(draft)
    if not nomination.player_id:
        return None
    return {
        "player_id": nomination.player_id,
        "highest_offer": nomination.highest_offer,
        "offering_slot": nomination.offering_slot,
    }


def _bid_log_path(draft_id: str) -> Path:
    return REPO_ROOT / "data" / f"bid-log-{draft_id}.json"


def _draft_save_path(draft_id: str) -> Path:
    return REPO_ROOT / "data" / f"draft-{draft_id}.json"


def _append_bid_log(path: Path, player_id: str, seat: int, amount: int) -> None:
    """Append one bid rung for `player_id`, only if it differs from the last
    recorded rung -- see docs/spec/analysis/01-bid-trends.md's format:
    `{player_id: [{seat, amount}, ...]}`, `seat` 1-indexed (matching
    `offering_slot`). Sleeper exposes only the current high bid, so this
    ladder is a sample of the bidding reconstructed from poll history, not a
    transcript of it -- a rung raised and outbid between two polls is never
    recorded.
    """
    log: Dict[str, List[Dict[str, int]]] = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    )
    rungs = log.setdefault(player_id, [])
    if rungs and rungs[-1]["seat"] == seat and rungs[-1]["amount"] == amount:
        return
    rungs.append({"seat": seat, "amount": amount})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")


def _save_draft(path: Path, board: "Board") -> None:
    """Durable mirror of the draft -- the shape
    docs/spec/analysis/01-bid-trends.md's guide already documents for
    `data/draft-<id>.json`: `{me?, seat_names?, picks: [{player_id, amount,
    draft_slot, pick_no, position}]}`. Atomic (write to a temp file, then
    rename) so a crash mid-write never leaves a half-written file
    `load_saved_draft`/`--picks-file` could choke on. `seat_names` is
    0-indexed (matching `board.seat_users`); `me` is 1-indexed, matching
    `--me` and Sleeper's own `draft_slot` convention.
    """
    picks = []
    for raw in board.raw_picks:
        meta = raw.get("metadata") or {}
        picks.append(
            {
                "player_id": str(raw.get("player_id") or meta.get("player_id")),
                "amount": int(meta.get("amount") or 0),
                "draft_slot": raw.get("draft_slot"),
                "pick_no": raw.get("pick_no"),
                "position": meta.get("position"),
            }
        )
    envelope: Dict[str, Any] = {
        "picks": picks,
        "seat_names": {
            str(seat_id): identity.get("display_name") or identity.get("username")
            for seat_id, identity in board.seat_users.items()
        },
    }
    if board.my_seat is not None:
        envelope["me"] = board.my_seat + 1

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_saved_draft(
    path: Path, config: LeagueConfig
) -> Optional[Tuple[LeagueState, List[Dict[str, Any]]]]:
    """Load a saved envelope -- the same shape `_save_draft` writes, and the
    same shape `--picks-file` already reads -- so the board can seed from it
    on startup and work offline before the first poll lands. Returns
    `(state, picks)` in the internal pick shape (`player_id`/`position`/
    `amount`/`draft_slot`); `None` if the file doesn't exist.
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    picks = [
        {
            "player_id": p["player_id"],
            "position": p.get("position"),
            "amount": p["amount"],
            "draft_slot": p.get("draft_slot"),
        }
        for p in data.get("picks", [])
    ]
    return build_state(picks, config), picks


# --------------------------------------------------------------------------
# The time-travel scrubber -- see docs/spec/board/04-time-travel-scrubber.md.
# --------------------------------------------------------------------------

#: Folded into every frame's cache signature, so any change to what a frame
#: bakes in is a cache invalidation, not a manual purge -- bump this and
#: every persisted/in-memory frame misses and rebuilds against the current
#: shape. History: 1 -- initial frame cache (in-memory only).
FRAME_SCHEMA_VERSION = 1


def _prefix_sig(picks: List[Dict[str, Any]], n: int, seat_users: Dict[int, Dict[str, Any]]) -> str:
    """The cache key for a scrubbed frame: `FRAME_SCHEMA_VERSION`, the first
    `n` picks as `[index, player_id, amount]` triples, and the seat names a
    frame bakes into each roster. A frame depends only on its picks prefix
    -- the draft is append-only, so this stays valid as it grows.
    """
    triples = [[i, p["player_id"], p["amount"]] for i, p in enumerate(picks[:n])]
    names = {str(sid): u.get("display_name") or u.get("username") for sid, u in seat_users.items()}
    blob = {"v": FRAME_SCHEMA_VERSION, "picks": triples, "names": names}
    return json.dumps(blob, sort_keys=True)


def _sold_block(
    picks: List[Dict[str, Any]], n: int, seat_users: Dict[int, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """The pick that just sold at `n` -- what a scrubbed frame surfaces as
    `block` in place of a live nomination (a frozen frame has none). `None`
    at `n == 0` (the opening board, nothing sold yet).
    """
    if n <= 0 or n > len(picks):
        return None
    pick = picks[n - 1]
    draft_slot = pick.get("draft_slot")
    seat_id = int(draft_slot) - 1 if draft_slot is not None else None
    identity = seat_users.get(seat_id, {}) if seat_id is not None else {}
    return {
        "player_id": pick["player_id"],
        "position": pick.get("position"),
        "amount": pick.get("amount"),
        "seat": seat_id,
        "buyer": identity.get("display_name") or identity.get("username"),
        "sold": True,
    }


def _frame_store_dir(cache_key: Optional[str]) -> Optional[Path]:
    """`data/frames-<cache_key>/` -- `None` when there's no stable key to
    persist under (an inline paste has no draft id or file to name it by),
    in which case frames stay in-memory only for that run.
    """
    if not cache_key:
        return None
    return REPO_ROOT / "data" / f"frames-{cache_key}"


def _load_frame(store_dir: Optional[Path], n: int, sig: str) -> Optional[Dict[str, Any]]:
    """A persisted frame, or `None` on a miss -- no file, or its `sig`
    doesn't match the current one (schema bump, picks changed under it), so
    it rebuilds instead of serving a payload the current renderer can't
    read.
    """
    if store_dir is None:
        return None
    path = store_dir / f"{n}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("sig") != sig:
        return None
    return data.get("payload")


def _store_frame(store_dir: Optional[Path], n: int, sig: str, payload: Dict[str, Any]) -> None:
    """Persist a frame, atomically (temp file + rename)."""
    if store_dir is None:
        return
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / f"{n}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"sig": sig, "payload": payload}), encoding="utf-8")
    tmp.replace(path)


class Board:
    """Holds the config, the loaded projections, and the live state under a
    single-threaded refresh -- see docs/spec/board/01-live-data-ingestion.md.
    Two source modes: `file` (`--picks-file`, re-read on mtime change) and
    `draft` (`--draft-id`, polled -- see `poll_sleeper_once`). Identity comes
    from `seat_identity` over whatever `self._draft`/`self._users` currently
    hold (empty in `file` mode, real Sleeper data once `set_draft_id` runs)
    plus a pick's `picked_by`, filled out by `random_fill`.
    """

    def __init__(
        self,
        config: LeagueConfig,
        players: List[Player],
        w_floor: float,
        me_fallback: Optional[int] = None,
        matrix_top: int = DEFAULT_MATRIX_TOP,
    ):
        self.config = config
        self.players = players
        self.w_floor = w_floor
        self.me_fallback = me_fallback
        self.matrix_top = matrix_top
        self.mode = "file"
        self.picks_file: Optional[Path] = None
        self._mtime: Optional[float] = None
        self.draft_id: Optional[str] = None
        self._last_fingerprint: Optional[str] = None
        self._draft: Dict[str, Any] = {}
        self._users: List[Dict[str, Any]] = []
        self.raw_picks: List[Dict[str, Any]] = []
        #: The current picks, in draft order, internal shape -- what the
        #: scrubber replays prefixes of. See `get_payload_upto`.
        self.picks: List[Dict[str, Any]] = []
        #: {n: (prefix_sig, payload)} -- in-memory only so far (no disk
        #: persistence yet). See `get_payload_upto`.
        self._frame_cache: Dict[int, Tuple[str, Dict[str, Any]]] = {}
        self.state = LeagueState.opening(config)
        self.nomination: Optional[Dict[str, Any]] = None
        self._refresh_identity([])

    def _refresh_identity(self, picks: List[Dict[str, Any]]) -> None:
        self.seat_users = refresh_seat_identity(self._draft, self._users, picks, self.config)
        self.my_seat = resolve_my_seat(self.seat_users, self.me_fallback)
        self.divisions, self.seat_order = build_divisions(
            self.seat_users, self.config, self.my_seat
        )
        self.my_division = next((b["index"] for b in self.divisions if b["mine"]), None)

    def set_picks_file(self, path: Path) -> None:
        self.mode = "file"
        self.picks_file = path
        self._mtime = None
        self.refresh_from_file()

    def refresh_from_file(self) -> bool:
        """Re-read `picks_file` if its mtime changed. Returns whether it did."""
        if self.picks_file is None:
            return False
        mtime = self.picks_file.stat().st_mtime
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        data = json.loads(self.picks_file.read_text(encoding="utf-8"))
        picks = data.get("picks", [])
        self.state = build_state(picks, self.config)
        self.picks = picks
        self.nomination = data.get("nomination")
        self._refresh_identity(picks)
        return True

    def set_draft_id(self, draft_id: str) -> None:
        """Switch to `draft` mode and do the first poll. `league_id` comes
        off the draft itself -- one cheap extra `/draft` fetch to learn it,
        then `poll_sleeper_once(force=True)` does the real work. If a
        previously saved envelope exists (`data/draft-<id>.json`), it seeds
        `state` first, so the board has something to show even if the very
        first poll is slow or the first request lands before it returns.
        """
        self.mode = "draft"
        self.draft_id = draft_id
        self._last_fingerprint = None
        saved = load_saved_draft(_draft_save_path(draft_id), self.config)
        if saved is not None:
            self.state, picks = saved
            self.picks = picks
            self._refresh_identity(picks)
        seed = fetch_draft(draft_id)
        self._users = fetch_league_users(seed["league_id"])
        self.poll_sleeper_once(force=True)

    def poll_sleeper_once(self, force: bool = False) -> bool:
        """The cheap/expensive split -- see
        docs/spec/board/01-live-data-ingestion.md. A cheap `/draft` poll,
        `draft_fingerprint`-gated: only when it changes (or `force`) does
        this pay for the expensive `/draft/{id}/picks` refetch and rebuild
        `state`. On a refetch, also durably saves the draft
        (`data/draft-<id>.json`) and, if a player is on the block, appends
        its current high bid to the bid ladder (`data/bid-log-<id>.json`).
        Returns whether picks were actually refetched.

        A network failure never raises out of here -- it's printed and
        treated as "nothing changed", leaving `state` as it was (the last
        good poll, or whatever `load_saved_draft` seeded it with). A
        background poller that dies on the first hiccup is useless; a
        request handler that 500s because Sleeper had one slow response is
        worse than serving slightly stale data.
        """
        try:
            draft = fetch_draft(self.draft_id)
            fingerprint = draft_fingerprint(draft)
            if not force and fingerprint == self._last_fingerprint:
                return False
            raw_picks = fetch_draft_picks(self.draft_id)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see above
            print(f"poll_sleeper_once: {exc}", file=sys.stderr)
            return False

        self._last_fingerprint = fingerprint
        self._draft = draft
        self.raw_picks = raw_picks
        picks = [_pick_from_sleeper(p) for p in self.raw_picks]
        self.state = build_state(picks, self.config)
        self.picks = picks
        self.nomination = _nomination_from_sleeper(draft)
        self._refresh_identity(picks)
        _save_draft(_draft_save_path(self.draft_id), self)
        if self.nomination and self.nomination.get("offering_slot") is not None:
            _append_bid_log(
                _bid_log_path(self.draft_id),
                self.nomination["player_id"],
                self.nomination["offering_slot"],
                self.nomination.get("highest_offer") or 0,
            )
        return True

    def payload(self) -> Dict[str, Any]:
        if self.mode == "file" and self.picks_file is not None:
            self.refresh_from_file()
        # In "draft" mode the background poller (see `poller`) keeps state
        # current; a request here just reads whatever it last built.
        total = len(self.picks)
        result = build_payload(
            self.state,
            self.players,
            self.config,
            self.w_floor,
            seat_users=self.seat_users,
            divisions=self.divisions,
            seat_order=self.seat_order,
            my_seat=self.my_seat,
            my_division=self.my_division,
            matrix_top=self.matrix_top,
            nomination=self.nomination,
        )
        result["view"] = {"pick": total, "total": total, "live": True}
        return result

    @property
    def cache_key(self) -> Optional[str]:
        """What `data/frames-<cache_key>/` is named after -- the draft id in
        `draft` mode, the picks-file's stem in `file` mode, `None` for an
        inline paste (no stable id, so frames stay in-memory only).
        """
        if self.mode == "draft" and self.draft_id:
            return self.draft_id
        if self.mode == "file" and self.picks_file:
            return self.picks_file.stem
        return None

    def get_payload_upto(self, n: int) -> Dict[str, Any]:
        """The board as it stood after pick `n` -- see
        docs/spec/board/04-time-travel-scrubber.md. Checked in memory first,
        then on disk (`data/frames-<cache_key>/<n>.json`), both keyed by a
        prefix signature (`_prefix_sig`) so a stale entry -- a
        `FRAME_SCHEMA_VERSION` bump, or the seat names changing -- misses
        and rebuilds instead of serving a payload the current renderer can't
        read. `n` is clamped to `[0, total]`. Never mutates the live
        payload -- this builds its own residual state from a picks prefix,
        entirely separate from `self.state`.
        """
        total = len(self.picks)
        n = max(0, min(n, total))
        sig = _prefix_sig(self.picks, n, self.seat_users)

        cached = self._frame_cache.get(n)
        if cached is not None and cached[0] == sig:
            return cached[1]

        store_dir = _frame_store_dir(self.cache_key)
        disk_payload = _load_frame(store_dir, n, sig)
        if disk_payload is not None:
            self._frame_cache[n] = (sig, disk_payload)
            return disk_payload

        sub_state = build_state(self.picks[:n], self.config)
        result = build_payload(
            sub_state,
            self.players,
            self.config,
            self.w_floor,
            seat_users=self.seat_users,
            divisions=self.divisions,
            seat_order=self.seat_order,
            my_seat=self.my_seat,
            my_division=self.my_division,
            matrix_top=self.matrix_top,
            nomination=None,  # a scrubbed view has no live nomination
        )
        result["block"] = _sold_block(self.picks, n, self.seat_users)
        result["view"] = {"pick": n, "total": total, "live": n == total}
        self._frame_cache[n] = (sig, result)
        _store_frame(store_dir, n, sig, result)
        return result


TEMPLATES = Path(__file__).resolve().parent / "templates"
BOARD_TEMPLATE_PATH = TEMPLATES / "board_slides.html"


def load_board_page() -> str:
    """The deck's HTML, wrapped in the minimal skeleton a `file://`/browser
    `GET` needs -- the template itself is a fragment (`<title>`, `<style>`,
    markup, `<script>`, no `<html>`/`<head>`/`<body>`), same convention as
    `python/scripts/templates/draft_demo.html`. Re-read on every call rather
    than cached, so a template edit takes effect without restarting the
    server -- it's a small file and this is a dev-facing tool, not a
    high-QPS endpoint.
    """
    fragment = BOARD_TEMPLATE_PATH.read_text(encoding="utf-8")
    return f"<!doctype html>\n<html lang=\"en\">\n<meta charset=\"utf-8\" />\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n{fragment}\n</html>\n"


def make_handler(board: Board):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A002 -- quiet by default
            pass

        def _send_json(self, body: Dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 -- stdlib method name
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/state.json":
                query = urllib.parse.parse_qs(parsed.query)
                upto = query.get("upto")
                if upto:
                    self._send_json(board.get_payload_upto(int(upto[0])))
                else:
                    self._send_json(board.payload())
            elif parsed.path in ("/board", "/"):
                self._send_html(load_board_page())
            elif self.path == "/health":
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def poller(
    board: "Board",
    idle_interval: float,
    live_interval: float,
    stop_event: threading.Event,
) -> None:
    """Background loop driving `Board.poll_sleeper_once` at an adaptive
    cadence -- see docs/spec/board/01-live-data-ingestion.md. `live_interval`
    (fast) while a player is on the block, `idle_interval` (slow) otherwise:
    latency is only felt during active bidding, and a missed raise can't be
    recovered, so the fast cadence only runs when it actually matters. Both
    rates are localhost-only Sleeper calls, so the fast one is essentially
    free.
    """
    while not stop_event.is_set():
        board.poll_sleeper_once()
        interval = live_interval if board.nomination is not None else idle_interval
        stop_event.wait(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--picks-file", type=Path)
    parser.add_argument("--draft-id", type=str, default=LEAGUE_CONFIG.draft_id)
    parser.add_argument("--me", type=int, default=None, help="1-indexed fallback seat")
    parser.add_argument("--season", type=int, default=LEAGUE_CONFIG.season)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--w-floor", type=float, default=DEFAULT_W_FLOOR)
    parser.add_argument("--matrix-top", type=int, default=DEFAULT_MATRIX_TOP)
    parser.add_argument("--poll", type=float, default=0.75, help="idle poll interval, seconds")
    parser.add_argument(
        "--poll-live", type=float, default=0.2, help="poll interval while a player is on the block"
    )
    parser.add_argument(
        "--print-seats",
        action="store_true",
        help="fetch --draft-id's managers, print seat/name/username, and exit",
    )
    args = parser.parse_args()

    if args.print_seats:
        draft = fetch_draft(args.draft_id)
        users = fetch_league_users(draft["league_id"])
        print_seats(draft, users)
        return

    config = LEAGUE_CONFIG
    players = load_players_from_csv(projections_csv_path(args.season))
    board = Board(config, players, args.w_floor, me_fallback=args.me, matrix_top=args.matrix_top)

    if args.picks_file:
        board.set_picks_file(args.picks_file)
        print(f"Serving on http://127.0.0.1:{args.port}/state.json (picks: {args.picks_file})")
    else:
        board.set_draft_id(args.draft_id)
        stop_event = threading.Event()
        thread = threading.Thread(
            target=poller,
            args=(board, args.poll, args.poll_live, stop_event),
            daemon=True,
        )
        thread.start()
        print(
            f"Serving on http://127.0.0.1:{args.port}/state.json "
            f"(polling draft {args.draft_id}, idle {args.poll}s / live {args.poll_live}s)"
        )

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(board))
    server.serve_forever()


if __name__ == "__main__":
    main()
