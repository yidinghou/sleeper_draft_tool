"""Board · Sleeper polling -- see docs/spec/board/01-live-data-ingestion.md.

`fetch_draft`/`fetch_draft_picks`/`fetch_league_users` are monkeypatched to
canned Sleeper-shaped responses, so this pins the fingerprint-gating and the
pick-conversion logic without any network access. What it can't verify is a
live run against a real Sleeper draft's actual response quirks -- that's a
manual smoke test, not something this suite can cover.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import draft_board  # noqa: E402
from draft_board import Board  # noqa: E402

from vorp.league.config import LEAGUE_CONFIG  # noqa: E402


def _players():
    from vorp.csv_loader import load_players_from_csv, projections_csv_path

    return load_players_from_csv(projections_csv_path(LEAGUE_CONFIG.season))


USERS = [
    {"user_id": "u1", "username": "alice", "display_name": "Alice"},
    {"user_id": "u2", "username": "bob", "display_name": "Bob"},
]


def _draft(*, status="in_progress", nominated=None, league_id="l1", draft_order=None):
    metadata = {}
    if nominated:
        metadata.update(nominated)
    return {
        "draft_id": "d1",
        "league_id": league_id,
        "status": status,
        "draft_order": draft_order,
        "metadata": metadata,
    }


def _raw_pick(player_id, position, amount, draft_slot):
    return {
        "draft_id": "d1",
        "draft_slot": draft_slot,
        "player_id": player_id,
        "metadata": {"amount": str(amount), "player_id": player_id, "position": position},
    }


@pytest.fixture(autouse=True)
def _patched_sleeper(monkeypatch):
    """Canned by default: an empty draft with no picks. Individual tests
    override via monkeypatch.setattr after this fixture runs.
    """
    monkeypatch.setattr(draft_board, "fetch_draft", lambda draft_id: _draft())
    monkeypatch.setattr(draft_board, "fetch_draft_picks", lambda draft_id: [])
    monkeypatch.setattr(draft_board, "fetch_league_users", lambda league_id: USERS)
    yield


def _board():
    return Board(LEAGUE_CONFIG, _players(), w_floor=1.0, matrix_top=5)


def test_set_draft_id_switches_to_draft_mode_and_polls_once(monkeypatch):
    board = _board()
    board.set_draft_id("d1")
    assert board.mode == "draft"
    assert board.draft_id == "d1"


def test_poll_sleeper_once_skips_the_expensive_refetch_when_fingerprint_unchanged(monkeypatch):
    calls = {"picks": 0}

    def fake_picks(draft_id):
        calls["picks"] += 1
        return []

    monkeypatch.setattr(draft_board, "fetch_draft_picks", fake_picks)
    board = _board()
    board.set_draft_id("d1")  # first poll: force=True, always refetches
    assert calls["picks"] == 1

    changed = board.poll_sleeper_once()  # same fingerprint (status unchanged)
    assert changed is False
    assert calls["picks"] == 1  # not refetched


def test_poll_sleeper_once_refetches_when_the_fingerprint_changes(monkeypatch):
    state = {"status": "in_progress"}
    calls = {"picks": 0}

    def fake_draft(draft_id):
        return _draft(status=state["status"])

    def fake_picks(draft_id):
        calls["picks"] += 1
        return []

    monkeypatch.setattr(draft_board, "fetch_draft", fake_draft)
    monkeypatch.setattr(draft_board, "fetch_draft_picks", fake_picks)

    board = _board()
    board.set_draft_id("d1")
    assert calls["picks"] == 1

    state["status"] = "complete"  # changes the fingerprint
    changed = board.poll_sleeper_once()
    assert changed is True
    assert calls["picks"] == 2


def test_poll_sleeper_once_converts_sleeper_picks_into_residual_state(monkeypatch):
    monkeypatch.setattr(
        draft_board,
        "fetch_draft_picks",
        lambda draft_id: [_raw_pick("4881", "QB", 39, 3)],
    )
    board = _board()
    board.set_draft_id("d1")

    seat2 = next(s for s in board.state.seats if s.seat_id == 2)  # draft_slot 3 -> seat 2
    assert {b.player_id for b in seat2.bought} == {"4881"}
    assert seat2.spent() == 39


def test_poll_sleeper_once_picks_up_a_live_nomination(monkeypatch):
    monkeypatch.setattr(
        draft_board,
        "fetch_draft",
        lambda draft_id: _draft(
            nominated={
                "nominated_player_id": "4881",
                "highest_offer": "42",
                "offering_slot": "5",
            }
        ),
    )
    board = _board()
    board.set_draft_id("d1")
    assert board.nomination == {"player_id": "4881", "highest_offer": 42, "offering_slot": 5}


def test_poll_sleeper_once_nomination_is_none_when_board_is_empty():
    board = _board()
    board.set_draft_id("d1")
    assert board.nomination is None


def test_set_draft_id_resolves_real_seat_identity(monkeypatch):
    monkeypatch.setattr(
        draft_board,
        "fetch_draft",
        lambda draft_id: _draft(draft_order={"u1": 1, "u2": 2}),
    )
    board = _board()
    board.set_draft_id("d1")
    assert board.seat_users[0]["user_id"] == "u1"
    assert board.seat_users[1]["user_id"] == "u2"


def test_payload_in_draft_mode_does_not_poll_synchronously(monkeypatch):
    calls = {"draft": 0}

    def counting_fetch_draft(draft_id):
        calls["draft"] += 1
        return _draft()

    monkeypatch.setattr(draft_board, "fetch_draft", counting_fetch_draft)
    board = _board()
    board.set_draft_id("d1")
    before = calls["draft"]
    board.payload()
    board.payload()
    # payload() must not itself hit the network in draft mode -- that's the
    # poller thread's job (Phase A commit 3).
    assert calls["draft"] == before
