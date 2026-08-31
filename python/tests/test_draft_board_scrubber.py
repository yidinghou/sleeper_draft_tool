"""Board · the time-travel scrubber -- see
docs/spec/board/04-time-travel-scrubber.md.

Covers `get_payload_upto`, `_prefix_sig`, and `_sold_block` -- in-memory
memoization only so far (no disk persistence yet, that's the next commit).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import draft_board  # noqa: E402
from draft_board import Board  # noqa: E402

from vorp.league.config import LEAGUE_CONFIG  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "mock-draft-small.json"


def _players():
    from vorp.csv_loader import load_players_from_csv, projections_csv_path

    return load_players_from_csv(projections_csv_path(LEAGUE_CONFIG.season))


def _board():
    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0, matrix_top=5)
    board.set_picks_file(FIXTURE)
    return board


def test_get_payload_upto_replays_only_the_first_n_picks():
    board = _board()
    # The fixture's first two picks: player 19 ($10, seat 0), player 184
    # ($20, seat 1).
    frame = board.get_payload_upto(2)
    assert frame["spent"] == 30
    assert frame["view"] == {"pick": 2, "total": 4, "live": False}


def test_get_payload_upto_zero_is_the_opening_board():
    board = _board()
    frame = board.get_payload_upto(0)
    assert frame["spent"] == 0
    assert frame["block"] is None
    assert frame["view"]["live"] is False


def test_get_payload_upto_clamps_past_the_end_and_marks_live():
    board = _board()
    frame = board.get_payload_upto(999)
    assert frame["view"] == {"pick": 4, "total": 4, "live": True}
    assert frame["spent"] == board.state.spent()


def test_get_payload_upto_block_is_the_pick_that_just_sold():
    board = _board()
    frame = board.get_payload_upto(1)
    assert frame["block"]["player_id"] == "19"
    assert frame["block"]["sold"] is True
    assert frame["block"]["amount"] == 10
    assert frame["block"]["seat"] == 0  # draft_slot 1 -> seat 0


def test_get_payload_upto_is_memoized(monkeypatch):
    board = _board()
    calls = {"n": 0}
    real_price_board = draft_board.price_board

    def counting_price_board(*args, **kwargs):
        calls["n"] += 1
        return real_price_board(*args, **kwargs)

    monkeypatch.setattr(draft_board, "price_board", counting_price_board)
    board.get_payload_upto(2)
    board.get_payload_upto(2)
    assert calls["n"] == 1


def test_get_payload_upto_never_mutates_the_live_state():
    board = _board()
    live_spent_before = board.state.spent()
    board.get_payload_upto(1)
    assert board.state.spent() == live_spent_before


def test_prefix_sig_changes_when_frame_schema_version_bumps():
    picks = json.loads(FIXTURE.read_text())["picks"]
    sig_v1 = draft_board._prefix_sig(picks, 2, {})
    original = draft_board.FRAME_SCHEMA_VERSION
    try:
        draft_board.FRAME_SCHEMA_VERSION = original + 1
        sig_v2 = draft_board._prefix_sig(picks, 2, {})
    finally:
        draft_board.FRAME_SCHEMA_VERSION = original
    assert sig_v1 != sig_v2


def test_sold_block_none_at_pick_zero():
    picks = json.loads(FIXTURE.read_text())["picks"]
    assert draft_board._sold_block(picks, 0, {}) is None
