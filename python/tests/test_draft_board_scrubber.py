"""Board · the time-travel scrubber -- see
docs/spec/board/04-time-travel-scrubber.md.

Covers `get_payload_upto`, `_prefix_sig`, `_sold_block`, and the disk
persistence layer (`_load_frame`/`_store_frame`/`_frame_store_dir`).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "auction"))

import draft_board  # noqa: E402
from draft_board import Board  # noqa: E402

from vorp.league.config import LEAGUE_CONFIG  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "mock-draft-small.json"


@pytest.fixture(autouse=True)
def _redirect_frame_store(monkeypatch, tmp_path):
    """Every test in this file that persists frames must write into
    `tmp_path`, never this repo's real `data/frames-*/` -- `cache_key` for
    the fixture board is a stable `"mock-draft-small"` (the file's stem)
    every run, so without this, tests would collide with a real disk cache
    across runs (and pollute the repo).
    """
    monkeypatch.setattr(
        draft_board, "_frame_store_dir", lambda cache_key: (tmp_path / cache_key) if cache_key else None
    )
    yield


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


# --------------------------------------------------------------------------
# Disk persistence
# --------------------------------------------------------------------------


def test_get_payload_upto_persists_to_disk(tmp_path):
    board = _board()
    board.get_payload_upto(2)
    store_dir = draft_board._frame_store_dir(board.cache_key)
    assert (store_dir / "2.json").exists()


def test_a_fresh_board_loads_a_frame_from_disk_without_rebuilding(monkeypatch):
    # First board builds and persists frame 2.
    board_a = _board()
    board_a.get_payload_upto(2)

    # A brand-new Board instance, same cache_key (same picks-file stem) --
    # simulates a server restart. Its in-memory cache is empty, so a hit
    # must come from disk.
    calls = {"n": 0}
    real_price_board = draft_board.price_board

    def counting_price_board(*args, **kwargs):
        calls["n"] += 1
        return real_price_board(*args, **kwargs)

    monkeypatch.setattr(draft_board, "price_board", counting_price_board)
    board_b = _board()
    frame = board_b.get_payload_upto(2)
    assert calls["n"] == 0  # served from disk, never rebuilt
    assert frame["spent"] == 30


def test_a_frame_schema_version_bump_invalidates_a_stale_disk_frame(monkeypatch):
    board = _board()
    board.get_payload_upto(2)  # persists under the old FRAME_SCHEMA_VERSION

    original = draft_board.FRAME_SCHEMA_VERSION
    monkeypatch.setattr(draft_board, "FRAME_SCHEMA_VERSION", original + 1)

    calls = {"n": 0}
    real_price_board = draft_board.price_board

    def counting_price_board(*args, **kwargs):
        calls["n"] += 1
        return real_price_board(*args, **kwargs)

    monkeypatch.setattr(draft_board, "price_board", counting_price_board)
    board_b = _board()  # fresh in-memory cache too
    board_b.get_payload_upto(2)
    assert calls["n"] == 1  # the stale disk frame missed and rebuilt
