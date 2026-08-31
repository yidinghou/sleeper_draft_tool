#!/usr/bin/env python3
"""The live draft board server -- see docs/spec/board/index.md.

Steps 2 and 4 of docs/spec/board/guide.md's build order: the server skeleton,
`/state.json`, seat identity + divisions, and the per-seat bid matrix. This
is still a partial slice of the full rendering contract
(docs/spec/board/03-rendering-contract.md) -- pool/spent/spots_left/levels,
a priced player list, the bid matrix, and seat_users/divisions/seat_order/
my_seat/my_division, from a `--picks-file` replayed into a residual
`LeagueState`. Not yet built: `block` (needs a nomination source -- the
matrix's `force_ids` hook is there for it) and `my_plan` (needs
`plan_roster`, spec 09 -- not built). Sleeper polling (guide.md step 3) is
also follow-up work; today this only reads `--picks-file`, so identity is
resolved from `random_fill` plus whatever a pick's `picked_by` happens to
carry -- there is no real `draft`/`users` feed to seed pins from yet,
outside of `--print-seats`, which does its own one-shot fetch.

The matrix has no cache in front of it (that's guide.md step 6, not built),
so it runs one lineup solve per `(player, real seat)` pair on every
`/state.json` request -- `--matrix-top` (default 300) bounds it.

Usage: python scripts/draft_board.py --picks-file <path> [--me 3] [--port 8770]
                                     [--season 2026] [--w-floor 1.0]
                                     [--matrix-top 300]
       python scripts/draft_board.py --draft-id <id> --print-seats
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.board import price_board  # noqa: E402
from vorp.csv_loader import load_players_from_csv, projections_csv_path  # noqa: E402
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
from vorp.seat_value import price_from_value, seat_values  # noqa: E402
from vorp.sleeper_client import fetch_draft, fetch_league_users, seat_identity  # noqa: E402

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
) -> Dict[str, Any]:
    """The (still partial) `/state.json` payload -- see
    docs/spec/board/03-rendering-contract.md. The identity-derived keys
    (`seat_users`, `divisions`, `seat_order`, `my_seat`, `my_division`) are
    included only when the caller supplies them, so this stays a pure
    function callable without an identity source.
    """
    sold_ids = set(state.sold())
    remaining = [p for p in players if p.player_id not in sold_ids]
    by_id = {p.player_id: p for p in remaining}
    board = price_board(state, remaining, config, w_floor)

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
        "matrix": seat_matrix(state, remaining, players, board, matrix_top=matrix_top),
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


class Board:
    """Holds the config, the loaded projections, and the live state under a
    single-threaded refresh -- see docs/spec/board/01-live-data-ingestion.md.
    Only the `file` source mode is implemented so far, so identity is
    resolved from each pick's `picked_by` (usually absent from a hand-edited
    mock) plus `random_fill` -- there is no Sleeper `draft`/`users` source
    yet to seed real pins from.
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
        self.picks_file: Optional[Path] = None
        self._mtime: Optional[float] = None
        self.state = LeagueState.opening(config)
        self._refresh_identity([])

    def _refresh_identity(self, picks: List[Dict[str, Any]]) -> None:
        self.seat_users = refresh_seat_identity({}, [], picks, self.config)
        self.my_seat = resolve_my_seat(self.seat_users, self.me_fallback)
        self.divisions, self.seat_order = build_divisions(
            self.seat_users, self.config, self.my_seat
        )
        self.my_division = next((b["index"] for b in self.divisions if b["mine"]), None)

    def set_picks_file(self, path: Path) -> None:
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
        self._refresh_identity(picks)
        return True

    def payload(self) -> Dict[str, Any]:
        if self.picks_file is not None:
            self.refresh_from_file()
        return build_payload(
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
        )


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

        def do_GET(self) -> None:  # noqa: N802 -- stdlib method name
            if self.path == "/state.json":
                self._send_json(board.payload())
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--picks-file", type=Path)
    parser.add_argument("--draft-id", type=str, default=LEAGUE_CONFIG.draft_id)
    parser.add_argument("--me", type=int, default=None, help="1-indexed fallback seat")
    parser.add_argument("--season", type=int, default=LEAGUE_CONFIG.season)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--w-floor", type=float, default=DEFAULT_W_FLOOR)
    parser.add_argument("--matrix-top", type=int, default=DEFAULT_MATRIX_TOP)
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

    if not args.picks_file:
        parser.error("--picks-file is required (Sleeper polling isn't built yet)")

    config = LEAGUE_CONFIG
    players = load_players_from_csv(projections_csv_path(args.season))
    board = Board(config, players, args.w_floor, me_fallback=args.me, matrix_top=args.matrix_top)
    board.set_picks_file(args.picks_file)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(board))
    print(f"Serving on http://127.0.0.1:{args.port}/state.json (picks: {args.picks_file})")
    server.serve_forever()


if __name__ == "__main__":
    main()
