from dataclasses import replace

from vorp.league.config import LEAGUE_CONFIG, LeagueConfig
from vorp.replacement_level import ReplacementPlayer, calculate_replacement_levels

# A minimal league forcing real flex contention: 2 concrete RB slots,
# 2 concrete TE slots, and exactly 1 FLEX slot (RB/WR/TE eligible).
# teams=1 keeps the slot counts equal to the raw numbers below.
FLEX_CONTEST_LEAGUE = LeagueConfig(
    league_id="test",
    draft_id="test",
    season=2026,
    teams=1,
    budget=200,
    min_bid=1,
    starting_slots={"QB": 0, "RB": 2, "WR": 0, "TE": 2, "K": 0, "DEF": 0},
    flex_slots={"FLEX": 1, "REC_FLEX": 0, "SUPER_FLEX": 0},
    bench_slots=0,
)


def player(player_id: str, position: str, points: float) -> ReplacementPlayer:
    return ReplacementPlayer(player_id=player_id, position=position, points=points)


def test_a_strong_tight_end_class_claims_flex_slots_from_running_backs():
    # 2 concrete RB slots, 2 concrete TE slots, 1 contested FLEX slot.
    # The 3rd-best TE outscores the 3rd-best RB, so the TE claims the flex.
    players = [
        player("rb1", "RB", 100),
        player("rb2", "RB", 90),
        player("rb3", "RB", 20),  # loses the flex contest
        player("te1", "TE", 80),
        player("te2", "TE", 70),
        player("te3", "TE", 60),  # wins the flex contest
    ]

    result = calculate_replacement_levels(players, FLEX_CONTEST_LEAGUE)

    assert "te3" in result.selected_player_ids
    assert "rb3" not in result.selected_player_ids


def test_a_shallow_tight_end_class_yields_no_flex_claims_at_all():
    players = [
        player("rb1", "RB", 100),
        player("rb2", "RB", 90),
        player("rb3", "RB", 50),  # claims the flex
        player("te1", "TE", 80),
        player("te2", "TE", 70),
        player("te3", "TE", 10),  # too weak to claim anything past the concrete TE slots
    ]

    result = calculate_replacement_levels(players, FLEX_CONTEST_LEAGUE)

    assert "rb3" in result.selected_player_ids
    assert "te3" not in result.selected_player_ids


def test_replacement_level_is_the_best_player_left_outside_the_selected_set():
    # 12 teams, 1 starting TE each => 12 concrete TE slots. REC_FLEX (WR/TE)
    # is entirely claimed by wide receivers, so TE replacement is exactly
    # the 13th tight end.
    config = replace(
        LEAGUE_CONFIG,
        teams=12,
        starting_slots={"QB": 0, "RB": 0, "WR": 0, "TE": 1, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 1, "SUPER_FLEX": 0},
    )

    te_points = [220, 200, 180, 170, 165, 160, 155, 150, 148, 145, 143, 141, 140, 130]
    players = [player(f"te{i + 1}", "TE", pts) for i, pts in enumerate(te_points)]

    # 12 wide receivers, all outscoring every tight end, to claim every REC_FLEX.
    players += [player(f"wr{i + 1}", "WR", 300 - i) for i in range(12)]

    result = calculate_replacement_levels(players, config)

    assert result.by_position["TE"].replacement_level == 140


def test_a_position_that_can_never_start_has_no_selected_slots_and_no_replacement_level():
    players = [
        player("k1", "K", 150),
        player("k2", "K", 140),
        player("qb1", "QB", 300),
    ]

    result = calculate_replacement_levels(players, LEAGUE_CONFIG)

    assert result.by_position["K"].reachable is False
    assert result.by_position["K"].replacement_level is None
    assert "k1" not in result.selected_player_ids
    assert "k2" not in result.selected_player_ids
