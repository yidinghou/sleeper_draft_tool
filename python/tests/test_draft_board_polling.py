"""Board · Sleeper polling -- see docs/spec/board/01-live-data-ingestion.md.

`fetch_draft`/`fetch_draft_picks`/`fetch_league_users` are monkeypatched to
canned Sleeper-shaped responses, so this pins the fingerprint-gating and the
pick-conversion logic without any network access. What it can't verify is a
live run against a real Sleeper draft's actual response quirks -- that's a
manual smoke test, not something this suite can cover.
"""

import json
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
def _patched_sleeper(monkeypatch, tmp_path):
    """Canned by default: an empty draft with no picks. Individual tests
    override via monkeypatch.setattr after this fixture runs.

    Also redirects the save/bid-log paths into `tmp_path` -- otherwise every
    test using `set_draft_id`/`poll_sleeper_once` would write real files
    into this repo's `data/` directory.
    """
    monkeypatch.setattr(draft_board, "fetch_draft", lambda draft_id: _draft())
    monkeypatch.setattr(draft_board, "fetch_draft_picks", lambda draft_id: [])
    monkeypatch.setattr(draft_board, "fetch_league_users", lambda league_id: USERS)
    monkeypatch.setattr(draft_board, "_draft_save_path", lambda draft_id: tmp_path / f"draft-{draft_id}.json")
    monkeypatch.setattr(draft_board, "_bid_log_path", lambda draft_id: tmp_path / f"bid-log-{draft_id}.json")
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


# --------------------------------------------------------------------------
# _append_bid_log / _save_draft / load_saved_draft
# --------------------------------------------------------------------------


def test_append_bid_log_appends_a_new_rung(tmp_path):
    path = tmp_path / "bid-log.json"
    draft_board._append_bid_log(path, "4881", seat=3, amount=10)
    draft_board._append_bid_log(path, "4881", seat=5, amount=15)
    log = json.loads(path.read_text())
    assert log["4881"] == [{"seat": 3, "amount": 10}, {"seat": 5, "amount": 15}]


def test_append_bid_log_skips_an_unchanged_rung(tmp_path):
    path = tmp_path / "bid-log.json"
    draft_board._append_bid_log(path, "4881", seat=3, amount=10)
    draft_board._append_bid_log(path, "4881", seat=3, amount=10)  # same rung
    log = json.loads(path.read_text())
    assert log["4881"] == [{"seat": 3, "amount": 10}]


def test_append_bid_log_tracks_multiple_players_independently(tmp_path):
    path = tmp_path / "bid-log.json"
    draft_board._append_bid_log(path, "4881", seat=3, amount=10)
    draft_board._append_bid_log(path, "9509", seat=1, amount=20)
    log = json.loads(path.read_text())
    assert set(log) == {"4881", "9509"}


def test_save_and_load_saved_draft_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(
        draft_board,
        "fetch_draft_picks",
        lambda draft_id: [_raw_pick("4881", "QB", 39, 3)],
    )
    board = _board()
    board.set_draft_id("d1")  # writes to the redirected tmp_path via the fixture

    saved_path = tmp_path / "draft-d1.json"
    assert saved_path.exists()
    loaded = draft_board.load_saved_draft(saved_path, LEAGUE_CONFIG)
    assert loaded is not None
    state, picks = loaded
    seat2 = next(s for s in state.seats if s.seat_id == 2)
    assert {b.player_id for b in seat2.bought} == {"4881"}
    assert picks == [{"player_id": "4881", "position": "QB", "amount": 39, "draft_slot": 3}]


def test_load_saved_draft_returns_none_when_file_is_absent(tmp_path):
    assert draft_board.load_saved_draft(tmp_path / "nope.json", LEAGUE_CONFIG) is None


def test_set_draft_id_falls_back_to_a_saved_draft_when_the_first_poll_fails(monkeypatch, tmp_path):
    # The real payoff of load_saved_draft: if the very first live poll fails
    # (a network hiccup on startup), the board still has the last known real
    # state instead of reverting to the empty opening board.
    saved_path = tmp_path / "draft-d1.json"
    saved_path.write_text(
        json.dumps({"picks": [{"player_id": "4881", "position": "QB", "amount": 39, "draft_slot": 3}]})
    )
    monkeypatch.setattr(draft_board, "_draft_save_path", lambda draft_id: saved_path)

    def failing_fetch_draft(draft_id):
        raise RuntimeError("Sleeper API /draft failed: 503 Service Unavailable")

    board = _board()
    # set_draft_id's own seed = fetch_draft(draft_id) call (for league_id)
    # would also fail here, so patch it in after construction, right before
    # the poll that's actually under test.
    monkeypatch.setattr(draft_board, "fetch_draft", lambda draft_id: _draft())
    saved = draft_board.load_saved_draft(saved_path, LEAGUE_CONFIG)
    board.state, picks = saved
    board._refresh_identity(picks)
    board.draft_id = "d1"
    board.mode = "draft"

    monkeypatch.setattr(draft_board, "fetch_draft", failing_fetch_draft)
    changed = board.poll_sleeper_once(force=True)
    assert changed is False
    # State is untouched -- still the saved draft's, not reset to opening.
    seat2 = next(s for s in board.state.seats if s.seat_id == 2)
    assert {b.player_id for b in seat2.bought} == {"4881"}


def test_poll_sleeper_once_survives_a_picks_fetch_failure(monkeypatch):
    def failing_fetch_picks(draft_id):
        raise RuntimeError("Sleeper API /draft/d1/picks failed: 500 Internal Server Error")

    board = _board()
    board.set_draft_id("d1")  # succeeds (default fixtures)

    monkeypatch.setattr(draft_board, "fetch_draft_picks", failing_fetch_picks)
    # force=True to reach the (failing) picks fetch regardless of fingerprint.
    changed = board.poll_sleeper_once(force=True)
    assert changed is False  # never raised, and state is left as it was
    assert board.state.spent() == 0
