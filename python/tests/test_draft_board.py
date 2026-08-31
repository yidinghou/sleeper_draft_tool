"""Board · server skeleton -- see docs/spec/board/01-live-data-ingestion.md
and docs/spec/board/03-rendering-contract.md.

Covers `build_state`, `build_payload`, and `Board.refresh_from_file` -- the
minimal slice of the rendering contract implemented so far (pool/spent/
spots_left/levels/players). Seats, divisions, the bid matrix, `block`, and
`my_plan` aren't built yet; see the module docstring in draft_board.py.

`tests/fixtures/mock-draft-small.json` is a small hand-built fixture (4 real
players, 3 landing on real seats, 1 with no draft_slot) -- not the eventual
canonical `tests/fixtures/mock-draft.json` the full spec names (14 picks,
$602, a nomination, a bid log), which needs seat identity and bid-log
ingestion this increment doesn't build yet.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from draft_board import Board, build_payload, build_state  # noqa: E402

from vorp.league.config import LEAGUE_CONFIG  # noqa: E402
from vorp.league.teams import UNKNOWN_SEAT  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "mock-draft-small.json"


def _players():
    from vorp.csv_loader import load_players_from_csv, projections_csv_path

    return load_players_from_csv(projections_csv_path(LEAGUE_CONFIG.season))


def _picks():
    return json.loads(FIXTURE.read_text())["picks"]


def test_build_state_routes_picks_to_seats_by_draft_slot():
    state = build_state(_picks(), LEAGUE_CONFIG)
    seat0 = next(s for s in state.seats if s.seat_id == 0)  # draft_slot 1
    seat1 = next(s for s in state.seats if s.seat_id == 1)  # draft_slot 2
    assert {b.player_id for b in seat0.bought} == {"19", "147"}
    assert {b.player_id for b in seat1.bought} == {"184"}


def test_build_state_routes_no_draft_slot_to_unknown_seat():
    state = build_state(_picks(), LEAGUE_CONFIG)
    unknown = next(s for s in state.seats if s.seat_id == UNKNOWN_SEAT)
    assert {b.player_id for b in unknown.bought} == {"23"}


def test_build_state_pool_reconciles_to_the_residual_league():
    state = build_state(_picks(), LEAGUE_CONFIG)
    spent = 10 + 20 + 15 + 5
    assert state.spent() == spent
    assert state.pool() == LEAGUE_CONFIG.teams * LEAGUE_CONFIG.budget - spent
    # Only the 3 picks that landed on real seats (2 on slot 1, 1 on slot 2)
    # remove a slot; UNKNOWN_SEAT owns no roster template.
    assert state.spots_left() == LEAGUE_CONFIG.teams * LEAGUE_CONFIG.roster_size - 3


def test_build_payload_excludes_sold_players_and_reconciles():
    players = _players()
    state = build_state(_picks(), LEAGUE_CONFIG)
    payload = build_payload(state, players, LEAGUE_CONFIG, w_floor=1.0)

    sold_ids = {p["player_id"] for p in _picks()}
    payload_ids = {row["player_id"] for row in payload["players"]}
    assert sold_ids.isdisjoint(payload_ids)

    assert payload["pool"] == state.pool()
    assert payload["spots_left"] == state.spots_left()
    assert payload["spent"] == state.spent()
    assert sum(row["price"] for row in payload["players"]) == payload["pool"]


def test_board_refresh_from_file_rebuilds_state(tmp_path):
    picks_file = tmp_path / "picks.json"
    picks_file.write_text(json.dumps({"picks": []}))

    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0)
    board.set_picks_file(picks_file)
    assert board.state.spent() == 0

    picks_file.write_text(json.dumps({"picks": _picks()}))
    changed = board.refresh_from_file()
    assert changed is True
    assert board.state.spent() == 50


def test_board_refresh_from_file_is_a_noop_when_mtime_unchanged(tmp_path):
    picks_file = tmp_path / "picks.json"
    picks_file.write_text(json.dumps({"picks": []}))

    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0)
    board.set_picks_file(picks_file)
    assert board.refresh_from_file() is False


def test_board_payload_reflects_the_loaded_picks_file():
    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0)
    board.set_picks_file(FIXTURE)
    payload = board.payload()
    assert payload["spent"] == 50
    assert "19" not in {row["player_id"] for row in payload["players"]}
