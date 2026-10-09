from vorp.league.config import LeagueConfig
from vorp.league.waivers import (
    Claim,
    RosterState,
    resolve_waivers,
    roster_states_from_snapshot,
)


def roster(roster_id, budget=50, players=(), open_slots=1):
    return RosterState(
        roster_id=roster_id,
        name=f"Team {roster_id}",
        faab_budget_left=budget,
        player_ids=frozenset(players),
        open_slots=open_slots,
    )


def outcome_for(result, roster_id, add_player_id):
    for o in result.outcomes:
        if o.claim.roster_id == roster_id and o.claim.add_player_id == add_player_id:
            return o
    raise AssertionError("no matching outcome")


def test_single_claim_open_slot_no_drop_wins():
    rosters = {1: roster(1, budget=50, open_slots=1)}
    claims = [Claim(roster_id=1, add_player_id="A", drop_player_id=None, faab_bid=10)]

    result = resolve_waivers(rosters, claims)

    o = outcome_for(result, 1, "A")
    assert o.won and o.reason == "won"
    final = result.rosters[1]
    assert final.faab_budget_left == 40
    assert "A" in final.player_ids
    assert final.open_slots == 0


def test_higher_bid_wins_contested_player():
    rosters = {1: roster(1, budget=50, open_slots=1), 2: roster(2, budget=50, open_slots=1)}
    claims = [
        Claim(roster_id=1, add_player_id="A", drop_player_id=None, faab_bid=20),
        Claim(roster_id=2, add_player_id="A", drop_player_id=None, faab_bid=10),
    ]

    result = resolve_waivers(rosters, claims)

    assert outcome_for(result, 1, "A").won
    loser = outcome_for(result, 2, "A")
    assert not loser.won and loser.reason == "add_target_unavailable"
    assert result.rosters[2].faab_budget_left == 50
    assert "A" not in result.rosters[2].player_ids


def test_waterfall_double_drop_invalidates_second_claim():
    rosters = {1: roster(1, budget=100, players=("X",), open_slots=0)}
    claims = [
        Claim(roster_id=1, add_player_id="A", drop_player_id="X", faab_bid=50, priority=1),
        Claim(roster_id=1, add_player_id="B", drop_player_id="X", faab_bid=40, priority=2),
    ]

    result = resolve_waivers(rosters, claims)

    winner = outcome_for(result, 1, "A")
    loser = outcome_for(result, 1, "B")
    assert winner.won and winner.reason == "won"
    assert not loser.won and loser.reason == "drop_target_not_rostered"
    final = result.rosters[1]
    assert final.player_ids == frozenset({"A"})


def test_open_slot_claim_no_drop_consumes_slot():
    rosters = {1: roster(1, budget=50, open_slots=2)}
    claims = [Claim(roster_id=1, add_player_id="A", drop_player_id=None, faab_bid=5)]

    result = resolve_waivers(rosters, claims)

    assert outcome_for(result, 1, "A").won
    assert result.rosters[1].open_slots == 1


def test_insufficient_budget_fails():
    rosters = {1: roster(1, budget=5, open_slots=1)}
    claims = [Claim(roster_id=1, add_player_id="A", drop_player_id=None, faab_bid=10)]

    result = resolve_waivers(rosters, claims)

    o = outcome_for(result, 1, "A")
    assert not o.won and o.reason == "insufficient_budget"
    assert result.rosters[1].faab_budget_left == 5


def test_drop_required_when_no_open_slot():
    rosters = {1: roster(1, budget=50, open_slots=0)}
    claims = [Claim(roster_id=1, add_player_id="A", drop_player_id=None, faab_bid=10)]

    result = resolve_waivers(rosters, claims)

    o = outcome_for(result, 1, "A")
    assert not o.won and o.reason == "drop_required_no_open_slot"


def test_higher_bid_loses_to_lower_bid_with_drop_when_full():
    # Real week-2 result from league 1372724723108036608: roster 10 (full
    # roster, no drop offered) bid $7 on player 11435 and lost; roster 11
    # (also full) bid only $6 but paired it with a drop and won. Confirms
    # the drop requirement is enforced before bid comparison, not after.
    rosters = {
        10: roster(10, budget=50, open_slots=0),
        11: roster(11, budget=50, players=("8180",), open_slots=0),
    }
    claims = [
        Claim(roster_id=10, add_player_id="11435", drop_player_id=None, faab_bid=7),
        Claim(roster_id=11, add_player_id="11435", drop_player_id="8180", faab_bid=6),
    ]

    result = resolve_waivers(rosters, claims)

    loser = outcome_for(result, 10, "11435")
    winner = outcome_for(result, 11, "11435")
    assert not loser.won and loser.reason == "drop_required_no_open_slot"
    assert winner.won and winner.reason == "won"


def test_roster_states_from_snapshot():
    config = LeagueConfig(
        league_id="L", draft_id="D", season=2026, teams=2, budget=0, min_bid=0,
        starting_slots={"QB": 1}, flex_slots={}, bench_slots=1,
    )
    rosters_raw = [
        {"roster_id": 1, "owner_id": "u1", "players": ["A", "B"], "settings": {"waiver_budget_used": 15}},
    ]
    users_raw = [{"user_id": "u1", "display_name": "Alice"}]

    states = roster_states_from_snapshot(rosters_raw, users_raw, config, faab_budget_total=100)

    r = states[1]
    assert r.name == "Alice"
    assert r.faab_budget_left == 85
    assert r.player_ids == frozenset({"A", "B"})
    assert r.open_slots == max(0, config.roster_size - 2)
