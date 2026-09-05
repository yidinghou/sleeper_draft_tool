"""07 · Live draft board pricing core — see docs/spec/vorp/07-live-draft-board.md.

Two things pinned:

  reproduces `04`   with nothing sold, `price_board` reproduces
                    `progressive_blend`'s prices exactly, at the same
                    w_floor — it's the same model, handed the opening
                    league instead of a smaller one.
  one sale, one     a sale removes exactly the sold player from the rows
  slot, one price   and exactly one slot from the league's residual state,
                    and the pool drops by exactly the sale amount.
"""

import pytest

from vorp.board import price_board
from vorp.csv_loader import load_players_from_csv, projections_csv_path
from vorp.league.config import LEAGUE_CONFIG
from vorp.league.teams import LeagueState
from vorp.models import DEFAULT_W_FLOOR, progressive_blend


@pytest.fixture(scope="module")
def players():
    return load_players_from_csv(projections_csv_path(LEAGUE_CONFIG.season))


def test_reproduces_progressive_blend_with_nothing_sold(players):
    state = LeagueState.opening(LEAGUE_CONFIG)
    board = price_board(state, players, LEAGUE_CONFIG, DEFAULT_W_FLOOR)

    valuation = progressive_blend(DEFAULT_W_FLOOR)(players, LEAGUE_CONFIG)

    assert board["rows"].keys() == valuation.prices.keys()
    for pid, price in valuation.prices.items():
        assert board["rows"][pid]["price"] == price
    assert board["pool"] == LEAGUE_CONFIG.teams * LEAGUE_CONFIG.budget
    assert board["spots_left"] == LEAGUE_CONFIG.teams * LEAGUE_CONFIG.roster_size


def test_one_sale_removes_one_player_and_one_slot(players):
    opening = LeagueState.opening(LEAGUE_CONFIG)
    board_before = price_board(opening, players, LEAGUE_CONFIG, DEFAULT_W_FLOOR)

    # Sell the single most expensive player on the opening board.
    sold_id = max(board_before["rows"], key=lambda pid: board_before["rows"][pid]["price"])
    sold_position = next(p.position for p in players if p.player_id == sold_id)
    amount = 60

    after = opening.sell(sold_id, sold_position, amount, seat_id=0)
    remaining = [p for p in players if p.player_id != sold_id]
    board_after = price_board(after, remaining, LEAGUE_CONFIG, DEFAULT_W_FLOOR)

    assert sold_id not in board_after["rows"]
    assert board_after["pool"] == board_before["pool"] - amount
    assert board_after["spots_left"] == board_before["spots_left"] - 1
    # Reconciliation: the priced rows still sum to exactly the residual pool,
    # once every price is accounted for (05's `reconciles` law, mid-draft).
    assert sum(row["price"] for row in board_after["rows"].values()) == board_after["pool"]


def test_price_board_reconciles_with_nothing_sold(players):
    state = LeagueState.opening(LEAGUE_CONFIG)
    board = price_board(state, players, LEAGUE_CONFIG, DEFAULT_W_FLOOR)
    assert sum(row["price"] for row in board["rows"].values()) == board["pool"]
