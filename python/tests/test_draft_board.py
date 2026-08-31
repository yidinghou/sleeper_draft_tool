"""Board · server skeleton -- see docs/spec/board/01-live-data-ingestion.md
and docs/spec/board/03-rendering-contract.md.

Covers `build_state`, `build_payload`, `seat_matrix`, `plan_payload`,
`block_info`, and `Board.refresh_from_file` -- the partial slice of the
rendering contract implemented so far (pool/spent/spots_left/levels/players/
matrix/seat_users/divisions/seat_order/my_seat/my_division/my_plan/block).
`block`'s `market`/`wk3VorpD` fields aren't wired in (no data source); see
the module docstring in draft_board.py. Seat identity's own logic
(random_fill, build_divisions, resolve_my_seat) is covered in
test_seat_identity_and_divisions.py; `09`'s own properties (feasibility,
greedy optimality, etc.) are covered in test_optimal_roster.py -- this file
only checks that Board wires `my_plan`/`block` into the payload correctly.

Most tests pass a small `matrix_top` -- the matrix runs one lineup solve per
(player, real seat), so the shipped default (300, "the whole board") is slow
enough to matter across a whole test run.

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

from draft_board import Board, block_info, build_payload, build_state, seat_matrix  # noqa: E402

from vorp.board import price_board  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG  # noqa: E402
from vorp.league.teams import UNKNOWN_SEAT  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "mock-draft-small.json"
NOMINATION_FIXTURE = Path(__file__).parent / "fixtures" / "mock-draft-with-nomination.json"


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
    payload = build_payload(state, players, LEAGUE_CONFIG, w_floor=1.0, matrix_top=5)

    sold_ids = {p["player_id"] for p in _picks()}
    payload_ids = {row["player_id"] for row in payload["players"]}
    assert sold_ids.isdisjoint(payload_ids)

    assert payload["pool"] == state.pool()
    assert payload["spots_left"] == state.spots_left()
    assert payload["spent"] == state.spent()
    assert sum(row["price"] for row in payload["players"]) == payload["pool"]
    assert len(payload["matrix"]) == 5


def test_board_refresh_from_file_rebuilds_state(tmp_path):
    picks_file = tmp_path / "picks.json"
    picks_file.write_text(json.dumps({"picks": []}))

    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0, matrix_top=5)
    board.set_picks_file(picks_file)
    assert board.state.spent() == 0

    picks_file.write_text(json.dumps({"picks": _picks()}))
    changed = board.refresh_from_file()
    assert changed is True
    assert board.state.spent() == 50


def test_board_refresh_from_file_is_a_noop_when_mtime_unchanged(tmp_path):
    picks_file = tmp_path / "picks.json"
    picks_file.write_text(json.dumps({"picks": []}))

    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0, matrix_top=5)
    board.set_picks_file(picks_file)
    assert board.refresh_from_file() is False


def test_board_payload_reflects_the_loaded_picks_file():
    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0, matrix_top=5)
    board.set_picks_file(FIXTURE)
    payload = board.payload()
    assert payload["spent"] == 50
    assert "19" not in {row["player_id"] for row in payload["players"]}


def test_seat_matrix_caps_rows_at_matrix_top():
    players = _players()
    state = build_state(_picks(), LEAGUE_CONFIG)
    sold_ids = {p["player_id"] for p in _picks()}
    remaining = [p for p in players if p.player_id not in sold_ids]
    board = price_board(state, remaining, LEAGUE_CONFIG, w_floor=1.0)

    matrix = seat_matrix(state, remaining, players, board, matrix_top=5)
    assert len(matrix) == 5
    # Rows are the top 5 by price.
    top5_ids = sorted(board["rows"], key=lambda pid: -board["rows"][pid]["price"])[:5]
    assert {row["player_id"] for row in matrix} == set(top5_ids)


def test_seat_matrix_bids_cover_only_real_seats():
    players = _players()
    state = build_state(_picks(), LEAGUE_CONFIG)
    sold_ids = {p["player_id"] for p in _picks()}
    remaining = [p for p in players if p.player_id not in sold_ids]
    board = price_board(state, remaining, LEAGUE_CONFIG, w_floor=1.0)

    matrix = seat_matrix(state, remaining, players, board, matrix_top=3)
    real_seats = set(range(LEAGUE_CONFIG.teams))
    for row in matrix:
        assert set(row["bids"]) == real_seats
        assert UNKNOWN_SEAT not in row["bids"]


def test_seat_matrix_winner_is_the_highest_bidder_and_price_setter_is_second():
    players = _players()
    state = build_state(_picks(), LEAGUE_CONFIG)
    sold_ids = {p["player_id"] for p in _picks()}
    remaining = [p for p in players if p.player_id not in sold_ids]
    board = price_board(state, remaining, LEAGUE_CONFIG, w_floor=1.0)

    matrix = seat_matrix(state, remaining, players, board, matrix_top=3)
    for row in matrix:
        ranked = sorted(row["bids"].values(), reverse=True)
        if ranked and ranked[0] > 0:
            assert row["bids"][row["winner"]] == ranked[0]
        setter_bid = ranked[1] if len(ranked) > 1 else 0
        assert row["price_setter_bid"] == setter_bid
        expected = (setter_bid + 1) if setter_bid > 0 else row["price"]
        assert row["expected_price"] == expected


def test_board_payload_carries_a_full_identity_and_division_layout():
    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0, me_fallback=3, matrix_top=5)
    board.set_picks_file(FIXTURE)
    payload = board.payload()

    assert len(payload["seat_users"]) == LEAGUE_CONFIG.teams
    assert sorted(payload["seat_order"]) == list(range(LEAGUE_CONFIG.teams))
    assert payload["my_seat"] == 2  # --me 3, 1-indexed -> seat 2, 0-indexed
    assert payload["my_division"] is not None
    assert payload["divisions"][0]["mine"] is True


def test_board_payload_carries_my_plan_for_the_resolved_seat():
    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0, me_fallback=1, matrix_top=5)
    board.set_picks_file(FIXTURE)
    payload = board.payload()

    seat0 = next(s for s in board.state.seats if s.seat_id == 0)  # --me 1 -> seat 0
    plan = payload["my_plan"]
    assert plan["spend"] <= seat0.budget_left
    assert plan["points_after"] >= plan["points_before"]
    assert all(t["kind"] == "buy" for t in plan["targets"])
    assert all(f["kind"] == "fill" for f in plan["fills"])
    # fill_all=True (the board's own default) completes every open slot.
    assert plan["open_slots_after"] == 0


def test_my_plan_absent_when_my_seat_is_unresolved():
    payload = build_payload(
        build_state(_picks(), LEAGUE_CONFIG), _players(), LEAGUE_CONFIG, w_floor=1.0,
        matrix_top=5, my_seat=UNKNOWN_SEAT,
    )
    assert "my_plan" not in payload
    assert payload["my_seat"] == UNKNOWN_SEAT


def _nomination_picks():
    return json.loads(NOMINATION_FIXTURE.read_text())["picks"]


def test_block_is_none_when_no_nomination():
    payload = build_payload(
        build_state(_picks(), LEAGUE_CONFIG), _players(), LEAGUE_CONFIG, w_floor=1.0, matrix_top=5
    )
    assert payload["block"] is None


def test_block_info_carries_price_and_the_current_high_bid():
    players = _players()
    state = build_state(_nomination_picks(), LEAGUE_CONFIG)
    remaining = [p for p in players if p.player_id not in state.sold()]
    board = price_board(state, remaining, LEAGUE_CONFIG, w_floor=1.0)
    nomination = json.loads(NOMINATION_FIXTURE.read_text())["nomination"]

    block = block_info(nomination, remaining, board, matrix_rows=[])
    assert block["player_id"] == "1466"
    assert block["position"] == "TE"
    assert block["price"] == board["rows"]["1466"]["price"]
    assert block["highest_offer"] == 14
    assert block["offering_slot"] == 9


def test_block_bids_come_from_a_forced_matrix_row():
    players = _players()
    state = build_state(_nomination_picks(), LEAGUE_CONFIG)
    remaining = [p for p in players if p.player_id not in state.sold()]
    board = price_board(state, remaining, LEAGUE_CONFIG, w_floor=1.0)
    nomination = {"player_id": "1466", "highest_offer": 14, "offering_slot": 9}

    # Force the nominated player into a tiny matrix even though he's
    # nowhere near the top by price -- exactly what build_payload does.
    matrix = seat_matrix(state, remaining, players, board, matrix_top=1, force_ids=("1466",))
    assert any(r["player_id"] == "1466" for r in matrix)

    block = block_info(nomination, remaining, board, matrix)
    assert len(block["bids"]) == LEAGUE_CONFIG.teams


def test_block_is_none_for_an_already_sold_or_unpriced_player():
    players = _players()
    state = build_state(_picks(), LEAGUE_CONFIG)
    remaining = [p for p in players if p.player_id not in state.sold()]
    board = price_board(state, remaining, LEAGUE_CONFIG, w_floor=1.0)

    # "19" was sold in _picks(); a made-up id was never priced at all.
    assert block_info({"player_id": "19"}, remaining, board, matrix_rows=[]) is None
    assert block_info({"player_id": "not-a-real-id"}, remaining, board, matrix_rows=[]) is None


def test_board_payload_carries_block_from_the_picks_files_nomination():
    board = Board(LEAGUE_CONFIG, _players(), w_floor=1.0, matrix_top=5)
    board.set_picks_file(NOMINATION_FIXTURE)
    payload = board.payload()
    assert payload["block"]["player_id"] == "1466"
    assert len(payload["block"]["bids"]) == LEAGUE_CONFIG.teams
    # He was forced in even though he's not naturally in the top-5 matrix.
    assert any(row["player_id"] == "1466" for row in payload["matrix"])


def test_frame_store_dir_is_none_without_a_cache_key():
    from draft_board import _frame_store_dir

    assert _frame_store_dir(None) is None
    assert _frame_store_dir("") is None
    assert _frame_store_dir("some-id").name == "frames-some-id"
