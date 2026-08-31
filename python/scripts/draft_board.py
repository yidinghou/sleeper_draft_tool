#!/usr/bin/env python3
"""The live draft board server -- see docs/spec/board/index.md.

Step 2 of docs/spec/board/guide.md's build order: the server skeleton and
`/state.json`. This is a minimal slice of the full rendering contract
(docs/spec/board/03-rendering-contract.md) -- pool/spent/spots_left/levels
and a priced player list, from a `--picks-file` replayed into a residual
`LeagueState`. Not yet built: seats/divisions (need seat identity, guide.md
step 4), the per-seat bid matrix (needs seat_value.py over real seat
identities), `block` (needs a nomination source), and `my_plan` (needs
`plan_roster`, spec 09 -- not built). Sleeper polling (guide.md step 3) is
also follow-up work; today this only reads `--picks-file`.

Usage: python scripts/draft_board.py --picks-file <path> [--port 8770]
                                     [--season 2026] [--w-floor 1.0]
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.board import price_board  # noqa: E402
from vorp.csv_loader import load_players_from_csv, projections_csv_path  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG, LeagueConfig  # noqa: E402
from vorp.league.roster_fill import RosterFillPlayer as Player  # noqa: E402
from vorp.league.teams import LeagueState  # noqa: E402

DEFAULT_PORT = 8770
DEFAULT_W_FLOOR = 1.0


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


def build_payload(
    state: LeagueState, players: List[Player], config: LeagueConfig, w_floor: float
) -> Dict[str, Any]:
    """The (currently minimal) `/state.json` payload -- see
    docs/spec/board/03-rendering-contract.md.
    """
    sold_ids = set(state.sold())
    remaining = [p for p in players if p.player_id not in sold_ids]
    by_id = {p.player_id: p for p in remaining}
    board = price_board(state, remaining, config, w_floor)

    return {
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
    }


class Board:
    """Holds the config, the loaded projections, and the live state under a
    single-threaded refresh -- see docs/spec/board/01-live-data-ingestion.md.
    Only the `file` source mode is implemented so far.
    """

    def __init__(self, config: LeagueConfig, players: List[Player], w_floor: float):
        self.config = config
        self.players = players
        self.w_floor = w_floor
        self.picks_file: Optional[Path] = None
        self._mtime: Optional[float] = None
        self.state = LeagueState.opening(config)

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
        self.state = build_state(data.get("picks", []), self.config)
        return True

    def payload(self) -> Dict[str, Any]:
        if self.picks_file is not None:
            self.refresh_from_file()
        return build_payload(self.state, self.players, self.config, self.w_floor)


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
    parser.add_argument("--picks-file", type=Path, required=True)
    parser.add_argument("--season", type=int, default=LEAGUE_CONFIG.season)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--w-floor", type=float, default=DEFAULT_W_FLOOR)
    args = parser.parse_args()

    config = LEAGUE_CONFIG
    players = load_players_from_csv(projections_csv_path(args.season))
    board = Board(config, players, args.w_floor)
    board.set_picks_file(args.picks_file)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(board))
    print(f"Serving on http://127.0.0.1:{args.port}/state.json (picks: {args.picks_file})")
    server.serve_forever()


if __name__ == "__main__":
    main()
