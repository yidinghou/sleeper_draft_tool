"""09 · The best affordable roster — see docs/spec/vorp/09-optimal-roster.md.

Pins the "Done when" properties directly: no plan outspends its seat's
budget, `spend + reserve <= budget`, `len(targets) <= open slots`, and
`points_after >= points_before`; greedy equals the brute-forced optimum on a
flat-price board small enough to enumerate; `exclude_positions` and
`fill_all` behave as documented; an unknown seat gets an empty plan; a plan
is deterministic run to run.
"""

import itertools

import pytest

from vorp.board import price_board
from vorp.csv_loader import load_players_from_csv, projections_csv_path
from vorp.league.config import LEAGUE_CONFIG, LeagueConfig
from vorp.league.roster_fill import RosterFillPlayer
from vorp.league.teams import UNKNOWN_SEAT, LeagueState
from vorp.optimal_roster import plan_roster


@pytest.fixture(scope="module")
def players():
    return load_players_from_csv(projections_csv_path(LEAGUE_CONFIG.season))


@pytest.fixture(scope="module")
def priced(players):
    """A mid-draft residual state, plus the board's prices/replacement
    levels over what's left -- the inputs `plan_roster` actually spends
    against.
    """
    state = LeagueState.opening(LEAGUE_CONFIG)
    # A handful of real sales, spread across a few seats, so seat 0 (the one
    # under test) is mid-draft too: one RB and one WR bought already.
    board0 = price_board(state, players, LEAGUE_CONFIG, w_floor=1.0)
    top_rb = max(
        (pid for pid, row in board0["rows"].items() if _position(players, pid) == "RB"),
        key=lambda pid: board0["rows"][pid]["price"],
    )
    top_wr = max(
        (pid for pid, row in board0["rows"].items() if _position(players, pid) == "WR"),
        key=lambda pid: board0["rows"][pid]["price"],
    )
    state = state.sell(top_rb, "RB", board0["rows"][top_rb]["price"], seat_id=0)
    state = state.sell(top_wr, "WR", board0["rows"][top_wr]["price"], seat_id=1)

    remaining = [p for p in players if p.player_id not in state.sold()]
    board = price_board(state, remaining, LEAGUE_CONFIG, w_floor=1.0)
    prices = {pid: row["price"] for pid, row in board["rows"].items()}
    replacement = {pos: level["replacement"] for pos, level in board["levels"].items()}
    return state, remaining, prices, replacement


def _position(players, pid):
    return next(p.position for p in players if p.player_id == pid)


def test_no_plan_outspends_the_seats_budget(priced):
    state, remaining, prices, replacement = priced
    seat0 = next(s for s in state.seats if s.seat_id == 0)
    plan = plan_roster(state, 0, remaining, prices, replacement)
    assert plan.spend <= seat0.budget_left


def test_spend_plus_reserve_never_exceeds_budget(priced):
    state, remaining, prices, replacement = priced
    seat0 = next(s for s in state.seats if s.seat_id == 0)
    plan = plan_roster(state, 0, remaining, prices, replacement, fill_all=True)
    assert plan.spend + plan.reserve <= seat0.budget_left


def test_targets_never_exceed_open_slots(priced):
    state, remaining, prices, replacement = priced
    open_slots = sum(1 for s in state.full_roster_slots() if s.seat_id == 0)
    plan = plan_roster(state, 0, remaining, prices, replacement)
    assert len(plan.targets) <= open_slots


def test_points_after_never_below_points_before(priced):
    state, remaining, prices, replacement = priced
    plan = plan_roster(state, 0, remaining, prices, replacement)
    assert plan.points_after >= plan.points_before
    assert plan.points_gain == pytest.approx(plan.points_after - plan.points_before)


def test_excluded_positions_are_never_targeted(priced):
    state, remaining, prices, replacement = priced
    plan = plan_roster(state, 0, remaining, prices, replacement, exclude_positions=["RB", "WR"])
    positions = {t.position for t in plan.targets}
    assert positions.isdisjoint({"RB", "WR"})


def test_fill_all_completes_every_open_slot_and_tags_fills(priced):
    state, remaining, prices, replacement = priced
    open_slots = sum(1 for s in state.full_roster_slots() if s.seat_id == 0)
    plan = plan_roster(state, 0, remaining, prices, replacement, fill_all=True)
    assert len(plan.targets) + len(plan.fills) <= open_slots
    assert all(f.kind == "fill" for f in plan.fills)
    assert all(f.points_gain == 0.0 for f in plan.fills)
    # Every slot got filled -- there was plenty of budget and pool depth.
    assert plan.open_slots_after == 0


def test_excluded_positions_stay_open_even_under_fill_all(priced):
    state, remaining, prices, replacement = priced
    plan = plan_roster(
        state, 0, remaining, prices, replacement, exclude_positions=["K"], fill_all=True
    )
    positions = {t.position for t in plan.targets} | {f.position for f in plan.fills}
    assert "K" not in positions


def test_unknown_seat_returns_an_empty_plan(priced):
    state, remaining, prices, replacement = priced
    plan = plan_roster(state, UNKNOWN_SEAT, remaining, prices, replacement)
    assert plan.targets == ()
    assert plan.fills == ()


def test_missing_seat_id_returns_an_empty_plan(priced):
    state, remaining, prices, replacement = priced
    plan = plan_roster(state, 999, remaining, prices, replacement)
    assert plan.targets == ()


def test_plan_is_deterministic(priced):
    state, remaining, prices, replacement = priced
    plan_a = plan_roster(state, 0, remaining, prices, replacement)
    plan_b = plan_roster(state, 0, remaining, prices, replacement)
    assert plan_a.targets == plan_b.targets


# --------------------------------------------------------------------------
# Flat-price optimum -- a board small enough to brute-force.
# --------------------------------------------------------------------------

TINY_CONFIG = LeagueConfig(
    league_id="t",
    draft_id="t",
    season=2026,
    teams=1,
    budget=20,
    min_bid=1,
    starting_slots={"QB": 0, "RB": 2, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
    flex_slots={},
    bench_slots=0,
)

RB_CANDIDATES = [
    RosterFillPlayer(player_id="rbA", position="RB", points=50.0),
    RosterFillPlayer(player_id="rbB", position="RB", points=40.0),
    RosterFillPlayer(player_id="rbC", position="RB", points=30.0),
    RosterFillPlayer(player_id="rbD", position="RB", points=20.0),
]
FLAT_PRICES = {p.player_id: 5 for p in RB_CANDIDATES}
FLAT_REPLACEMENT = {"RB": 0.0}


def _brute_force_best(players_, prices, budget, slots_count):
    best_points = -1.0
    for r in range(0, min(len(players_), slots_count) + 1):
        for combo in itertools.combinations(players_, r):
            if sum(prices[p.player_id] for p in combo) > budget:
                continue
            points = sum(p.points for p in combo)
            best_points = max(best_points, points)
    return best_points


def test_greedy_equals_the_brute_forced_optimum_on_a_flat_price_board():
    state = LeagueState.opening(TINY_CONFIG)
    plan = plan_roster(state, 0, RB_CANDIDATES, FLAT_PRICES, FLAT_REPLACEMENT)

    optimum = _brute_force_best(RB_CANDIDATES, FLAT_PRICES, TINY_CONFIG.budget, slots_count=2)
    assert plan.points_after == optimum
    # The two best-by-points RBs fill the two identical RB slots exactly.
    assert {t.player_id for t in plan.targets} == {"rbA", "rbB"}
