"""08 · Seat bids — see docs/spec/vorp/08-seat-value.md.

Two laws, and the behaviours that make the model a refinement of the board
price rather than a different one:

  no illegal bid       every bid <= max_bid and <= budget; >= min_bid while
                       the seat can bid at all, 0 when it can't.
  no value w/o a slot  a player who reaches no startable slot is worth 0.

Explicit non-goal, so nobody writes the test: seat values do NOT reconcile to
the pool. `principles.reconciles` is a property of the board price. Twelve
seats each valuing the same player produce twelve numbers whose sum means
nothing.
"""

import pytest

from vorp.league.config import LEAGUE_CONFIG, LeagueConfig
from vorp.league.roster_fill import RosterFillPlayer
from vorp.league.teams import UNKNOWN_SEAT, LeagueState
from vorp.seat_value import (
    price_from_value,
    seat_bid,
    seat_values,
    seat_vorp,
    vorp_rate,
)

#: Replacement levels off the real 2026 board, so the numbers below are the
#: ones the shipped price list actually runs on.
REPLACEMENT = {"QB": 214.8, "RB": 137.9, "WR": 139.6, "TE": 129.5, "DEF": 96.0}

#: Eleven buys that fill eleven of this league's sixteen slots: the seven
#: concrete starters, all three flexes, and one bench spot. Leaves five open,
#: all bench, which is what makes the reserve arithmetic legible below.
ELEVEN_BUYS = [
    ("qb1", "QB"),
    ("rb1", "RB"),
    ("rb2", "RB"),
    ("wr1", "WR"),
    ("wr2", "WR"),
    ("te1", "TE"),
    ("def1", "DEF"),
    ("rb3", "RB"),  # FLEX
    ("wr3", "WR"),  # REC_FLEX
    ("qb2", "QB"),  # SUPER_FLEX
    ("rb4", "RB"),  # bench
]

#: A roster whose every RB-eligible starting slot is taken: QB and SUPER_FLEX
#: by two quarterbacks, RB/RB/FLEX by three backs, plus the receivers and the
#: tight end. Only REC_FLEX (WR/TE only) is left, so no back can reach a slot.
RB_SATURATED = [
    ("qb1", "QB", 300.0),
    ("qb2", "QB", 280.0),  # takes SUPER_FLEX
    ("rb1", "RB", 210.0),
    ("rb2", "RB", 190.0),
    ("rb3", "RB", 160.0),  # takes FLEX; the weakest RB starter
    ("wr1", "WR", 200.0),
    ("wr2", "WR", 185.0),
    ("te1", "TE", 170.0),
]


def player(player_id: str, position: str, points: float) -> RosterFillPlayer:
    return RosterFillPlayer(player_id=player_id, position=position, points=points)


def points_of(roster) -> dict:
    return {pid: pts for pid, _, pts in roster}


def seat_holding(roster, seat_id: int = 0) -> LeagueState:
    """A league where one seat has bought `roster`, each for a dollar."""
    state = LeagueState.opening(LEAGUE_CONFIG)
    for player_id, position, _ in roster:
        state = state.sell(player_id, position, 1, seat_id=seat_id)
    return state


def one_slot_config() -> LeagueConfig:
    """A league whose entire roster is a single running back, so "this seat
    has no spots left" is one sale away.
    """
    return LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=2,
        budget=50,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 1, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=0,
    )


# --------------------------------------------------------------------------
# Law: no value without a slot
# --------------------------------------------------------------------------


def test_a_back_who_reaches_no_slot_is_worth_nothing_to_that_seat():
    # The headline case. Every RB-eligible starting slot is filled by a better
    # back (or a quarterback in the superflex), so a mediocre fourth back adds
    # no points at all -- while the room still prices him off replacement.
    state = seat_holding(RB_SATURATED)
    candidate = player("rb9", "RB", 150.0)

    value = seat_vorp(state, 0, candidate, REPLACEMENT, points_of(RB_SATURATED))

    assert value == 0.0
    # The room disagrees, which is the whole point of the model.
    assert candidate.points - REPLACEMENT["RB"] == pytest.approx(12.1)


def test_bench_slots_add_nothing_but_an_upgrade_still_counts():
    # A full starting lineup leaves only bench slots, and a benched player
    # scores nothing -- so anyone who beats no current starter is worth 0. The
    # wrong answer is scoring bench slots too, which would quietly make a
    # seat's seventh receiver worth real money.
    #
    # What does NOT follow is "worth 0 to a full seat": a player good enough to
    # displace a starter is still worth the upgrade. The bench is what has no
    # value, not the seat.
    full_starters = RB_SATURATED + [("wr3", "WR", 150.0)]  # fills REC_FLEX
    state = seat_holding(full_starters)
    pts = points_of(full_starters)

    # Beats nobody in the lineup: pure bench depth, worth nothing.
    for pos, points in (("RB", 150.0), ("WR", 145.0), ("QB", 260.0)):
        value = seat_vorp(state, 0, player(f"x-{pos}", pos, points), REPLACEMENT, pts)
        assert value == 0.0, pos

    # Beats the weakest RB starter (160 in the flex): worth exactly the gap.
    upgrade = seat_vorp(state, 0, player("rbX", "RB", 250.0), REPLACEMENT, pts)
    assert upgrade == pytest.approx(90.0)


def test_an_empty_seat_values_a_player_at_exactly_his_league_vorp():
    # The anchor: with every slot holding an imputed replacement body, the
    # marginal points a player adds ARE points-over-replacement. Without this
    # the seat model would be a different model, not a refinement of 04.
    state = LeagueState.opening(LEAGUE_CONFIG)

    for pos in ("QB", "RB", "WR", "TE", "DEF"):
        candidate = player("x", pos, REPLACEMENT[pos] + 40.0)
        value = seat_vorp(state, 0, candidate, REPLACEMENT, {})
        assert value == pytest.approx(40.0), pos


#: Nine players for ten slots: one QB, three RBs, three WRs, a TE and a DEF.
#: Exactly the shape that has more than one maximum matching -- the leftover
#: slot can be the REC_FLEX or the SUPER_FLEX, and they are not worth the same
#: when a free body fills them.
NINE_FOR_TEN = [
    ("qb1", "QB", 283.7),
    ("rb1", "RB", 192.5),
    ("rb2", "RB", 192.0),
    ("rb3", "RB", 190.1),
    ("wr1", "WR", 194.9),
    ("wr2", "WR", 187.7),
    ("wr3", "WR", 187.7),
    ("te1", "TE", 132.5),
    ("def1", "DEF", 98.0),
]


def test_the_lineup_leaves_the_slot_a_free_body_fills_best():
    # Regression. `assign_to_slots` maximizes the COUNT of players seated, not
    # the points on the field, and those diverge the moment an unfilled slot is
    # worth something. With nine players in ten slots, leaving SUPER_FLEX to a
    # free quarterback (214.8) beats leaving REC_FLEX to a free receiver
    # (139.6) by 75 points -- but both seat nine men, so the matching alone
    # cannot tell them apart.
    #
    # Scoring empty slots after the fact took whichever matching Kuhn's
    # happened to return and priced an elite back at 160.3 instead of 109.8.
    # Putting the free bodies in the pool restores the transversal matroid the
    # greedy fill is optimal over.
    state = seat_holding(NINE_FOR_TEN)
    pts = points_of(NINE_FOR_TEN)

    elite_back = seat_vorp(state, 0, player("rbX", "RB", 299.9), REPLACEMENT, pts)

    # He displaces the weakest real starter (190.1), NOT a free receiver at
    # 139.6 -- the free quarterback in the superflex is worth more than the
    # back, so the back is what gives way.
    assert elite_back == pytest.approx(109.8)
    assert 299.9 - elite_back == pytest.approx(190.1)


def test_a_superflex_holds_a_free_quarterback_so_quarterbacks_face_a_high_bar():
    # The flip side, and the reason superflex leagues price quarterbacks the
    # way they do: the open slot is not empty, it holds the best body a dollar
    # buys, and for a QB/RB/WR/TE slot that is a quarterback at 214.8. A back
    # only has to beat this roster's weakest starter.
    state = seat_holding(NINE_FOR_TEN)
    pts = points_of(NINE_FOR_TEN)

    def bar_for(position: str) -> float:
        probe = 1_000_000.0
        value = seat_vorp(state, 0, player("probe", position, probe), REPLACEMENT, pts)
        return probe - value

    assert bar_for("QB") == pytest.approx(REPLACEMENT["QB"])  # 214.8
    assert bar_for("RB") == pytest.approx(190.1)  # the weakest back on the roster
    assert bar_for("QB") > bar_for("RB")


def test_an_upgrade_is_worth_what_he_displaces_not_what_the_room_pays():
    # RB slots full, but the candidate outscores the weakest RB starter (160).
    # He displaces that back rather than a replacement body, so he is worth
    # 200 - 160 = 40 here against 200 - 137.9 = 62.1 to the room.
    state = seat_holding(RB_SATURATED)
    candidate = player("rb0", "RB", 200.0)

    value = seat_vorp(state, 0, candidate, REPLACEMENT, points_of(RB_SATURATED))

    assert value == pytest.approx(40.0)
    assert value < candidate.points - REPLACEMENT["RB"]


def test_value_is_never_negative():
    state = seat_holding(RB_SATURATED)
    pts = points_of(RB_SATURATED)

    for pos in ("QB", "RB", "WR", "TE"):
        for points in (0.0, 50.0, 400.0):
            value = seat_vorp(state, 0, player("x", pos, points), REPLACEMENT, pts)
            assert value >= 0.0


# --------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------


def test_buying_a_back_never_raises_that_seat_s_value_for_the_next_one():
    # Diminishing returns, stated as a property. Also covers cross-position
    # flex contention: SUPER_FLEX makes QB/RB/WR/TE peers, so buying a receiver
    # can only lower a back's value, never raise it.
    candidate = player("rbX", "RB", 195.0)
    roster = []
    state = LeagueState.opening(LEAGUE_CONFIG)
    previous = seat_vorp(state, 0, candidate, REPLACEMENT, {})

    for player_id, position, points in RB_SATURATED:
        roster.append((player_id, position, points))
        state = state.sell(player_id, position, 1, seat_id=0)
        value = seat_vorp(state, 0, candidate, REPLACEMENT, points_of(roster))
        assert value <= previous + 1e-9, f"{position} {player_id} raised it"
        previous = value


def test_the_same_roster_bought_in_a_different_order_values_identically():
    # The payoff for running the matching rather than a greedy "concrete slot,
    # else flex, else bench" rule, which would be order-dependent. See
    # docs/spec/league/03-seats-and-sales.md.
    forwards = seat_holding(RB_SATURATED)
    backwards = seat_holding(list(reversed(RB_SATURATED)))
    pts = points_of(RB_SATURATED)
    candidates = [player("c1", "RB", 200.0), player("c2", "WR", 210.0), player("c3", "TE", 180.0)]

    a = seat_values(forwards, 0, candidates, REPLACEMENT, pts)
    b = seat_values(backwards, 0, candidates, REPLACEMENT, pts)

    assert a == b
    assert set(a) == {"c1", "c2", "c3"}


def test_a_seat_with_no_open_slots_may_still_want_a_player_but_cannot_bid():
    # Value and legality are separate questions, and this is where they come
    # apart. A seat with a full roster would genuinely improve by swapping its
    # back for a better one -- the lineup solve says so, and says by how much.
    # It still has nowhere to put him, so the bid is 0. Collapsing the two
    # would hide the upgrade; keeping them apart means the cap is the only
    # thing that ever refuses a bid.
    config = one_slot_config()
    state = LeagueState.opening(config).sell("rb1", "RB", 10, seat_id=0)

    value = seat_vorp(state, 0, player("rb2", "RB", 300.0), {"RB": 100.0}, {"rb1": 200.0})

    assert value == pytest.approx(100.0)  # 300 - the 200-point back he'd replace
    assert state.max_bid(0) == 0
    assert seat_bid(40, state, seat_id=0) == 0
    assert price_from_value(value, 0.391, state, 0) == 0


def test_the_unknown_seat_has_no_values_and_does_not_raise():
    # The synthetic seat for unattributed sales owns no roster template.
    state = LeagueState.opening(LEAGUE_CONFIG).sell("rb1", "RB", 40, seat_id=None)
    candidate = player("rb2", "RB", 200.0)

    assert seat_vorp(state, UNKNOWN_SEAT, candidate, REPLACEMENT, {"rb1": 210.0}) == 0.0
    assert seat_values(state, UNKNOWN_SEAT, [candidate], REPLACEMENT, {}) == {}
    assert seat_bid(60, state, seat_id=UNKNOWN_SEAT) == 0


def test_valuing_a_player_the_seat_already_owns_raises():
    # The delta is meaningless there, and silently returning 0 would read as
    # "he's worth nothing to you" rather than "you asked the wrong question".
    state = seat_holding(RB_SATURATED)
    owned = player("rb1", "RB", 210.0)

    with pytest.raises(ValueError, match="already owns"):
        seat_vorp(state, 0, owned, REPLACEMENT, points_of(RB_SATURATED))

    # seat_values skips them instead, because it is handed the whole board.
    values = seat_values(state, 0, [owned, player("rb9", "RB", 150.0)], REPLACEMENT, points_of(RB_SATURATED))
    assert set(values) == {"rb9"}


# --------------------------------------------------------------------------
# Law: no illegal bid
# --------------------------------------------------------------------------


def test_an_opening_seat_bids_the_board_price_untouched():
    # $200 and sixteen spots reserves fifteen dollars, so the cap is $185 --
    # far above any real price. The clamp has nothing to say and must say
    # nothing.
    state = LeagueState.opening(LEAGUE_CONFIG)

    assert state.max_bid(0) == 185
    assert seat_bid(60, state, seat_id=0) == 60
    assert seat_bid(200, state, seat_id=0) == 185
    assert seat_bid(0, state, seat_id=0) == LEAGUE_CONFIG.min_bid


def test_a_spent_down_seat_is_capped_below_what_it_still_holds():
    # Eleven buys for $170 leaves seat 0 with $30 and five open spots. It
    # cannot bid all $30: four of those spots still need a dollar each.
    state = LeagueState.opening(LEAGUE_CONFIG)
    for i, (player_id, position) in enumerate(ELEVEN_BUYS):
        state = state.sell(player_id, position, 20 if i == 0 else 15, seat_id=0)

    seat = next(s for s in state.seats if s.seat_id == 0)
    assert seat.budget_left == 30
    assert sum(1 for s in state.full_roster_slots() if s.seat_id == 0) == 5
    assert state.max_bid(0) == 26
    assert seat_bid(60, state, seat_id=0) == 26


def test_a_seat_that_cannot_cover_the_floor_is_out_rather_than_cheap():
    # Broke without being full. "Out" must not read as "can have him for a
    # dollar". Its unfilled spots stay in the league's demand either way
    # (docs/spec/league/03-seats-and-sales.md).
    state = LeagueState.opening(LEAGUE_CONFIG)
    for player_id, position in ELEVEN_BUYS[:10]:
        state = state.sell(player_id, position, 20, seat_id=0)

    assert next(s for s in state.seats if s.seat_id == 0).budget_left == 0
    assert state.max_bid(0) < LEAGUE_CONFIG.min_bid
    assert seat_bid(10, state, seat_id=0) == 0
    assert seat_bid(10, state, seat_id=1) == 10


def test_no_bid_ever_exceeds_the_cap_or_the_money_across_a_whole_draft():
    # The law, swept over a real sale sequence. Every seat runs the full eleven
    # buys at $17, so all twelve spend down to $13 with five spots open.
    state = LeagueState.opening(LEAGUE_CONFIG)

    for seat_id in range(LEAGUE_CONFIG.teams):
        for player_id, position in ELEVEN_BUYS:
            state = state.sell(f"{player_id}-s{seat_id}", position, 17, seat_id=seat_id)

            for seat in state.seats:
                if seat.seat_id == UNKNOWN_SEAT:
                    continue
                bid = seat_bid(500, state, seat.seat_id)
                assert bid <= state.max_bid(seat.seat_id)
                assert bid <= seat.budget_left
                assert bid == 0 or bid >= LEAGUE_CONFIG.min_bid

    assert all(s.budget_left == 13 for s in state.seats)


def test_the_dollar_conversion_floors_and_then_caps():
    # $0.391/pt is the opening 2026 rate. 40 points of value is $16.64 of
    # margin, floored to $16 and added to the $1 floor -- never rounded up to
    # a bid the model has just called too dear.
    state = LeagueState.opening(LEAGUE_CONFIG)

    assert price_from_value(40.0, 0.391, state, 0) == 16
    assert price_from_value(62.1, 0.391, state, 0) == 25
    assert price_from_value(0.0, 0.391, state, 0) == LEAGUE_CONFIG.min_bid
    # A value the seat cannot afford still comes back legal.
    assert price_from_value(10_000.0, 0.391, state, 0) == 185


def test_the_exchange_rate_is_the_one_the_board_price_runs_on():
    # Pool after every priced player's floor, over total margin.
    weights = {"a": 60.0, "b": 40.0}
    assert vorp_rate(pool=202, weights=weights, min_bid=1) == pytest.approx(2.0)
    assert vorp_rate(pool=100, weights={}, min_bid=1) == 0.0
