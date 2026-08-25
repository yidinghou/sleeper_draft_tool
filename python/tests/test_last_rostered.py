from vorp.last_rostered import LastRosteredPlayer, calculate_last_rostered_levels
from vorp.league_config import LEAGUE_CONFIG, LeagueConfig
from vorp.replacement_level import calculate_replacement_levels


def player(player_id: str, position: str, points: float) -> LastRosteredPlayer:
    return LastRosteredPlayer(player_id=player_id, position=position, points=points)


def test_a_position_with_no_concrete_slot_can_still_be_rostered_off_the_bench():
    # WR has no concrete starting slot here, but IS flex-eligible (FLEX
    # takes RB/WR/TE), so it's part of this league's draftable pool and can
    # therefore also win a bench slot. K, by contrast, has no footprint
    # anywhere in this template — no concrete slot, no flex — so it stays
    # out of the draftable pool entirely, bench included.
    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=200,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 1, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 1, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=1,
    )

    players = [
        player("rb1", "RB", 100),  # takes the one starting RB slot
        player("wr1", "WR", 90),  # wins the FLEX
        player("wr2", "WR", 80),  # wins the bench slot, despite WR having no concrete slot at all
        player("k1", "K", 70),  # loses out — K has no footprint in this template anywhere
    ]

    result = calculate_last_rostered_levels(players, config)

    assert "wr2" in result.selected_player_ids
    assert result.by_position["WR"].reachable is True
    assert "k1" not in result.selected_player_ids
    assert result.by_position["K"].reachable is False


def test_a_position_with_real_bench_depth_has_a_lower_last_rostered_level_than_its_replacement_level():
    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=200,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 2, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=3,
    )

    rb_points = [100, 90, 80, 70, 60, 50]
    players = [player(f"rb{i + 1}", "RB", pts) for i, pts in enumerate(rb_points)]

    replacement = calculate_replacement_levels(players, config)
    last_rostered = calculate_last_rostered_levels(players, config)

    assert replacement.by_position["RB"].replacement_level == 80  # rb3, first past the 2 starting slots
    assert last_rostered.by_position["RB"].last_rostered_level == 50  # rb6, first past all 5 roster spots
    assert last_rostered.by_position["RB"].last_rostered_level < replacement.by_position["RB"].replacement_level
    assert last_rostered.by_position["RB"].selected_count == 5


def test_defenses_are_streamed_never_benched_no_matter_how_they_project():
    # A backup defense projected to outscore literally everything else on
    # the board still doesn't win a bench slot: DEF is excluded from bench
    # eligibility entirely, because real managers stream it off waivers
    # rather than draft depth at it.
    players = [player(f"def{i + 1}", "DEF", 500 - i) for i in range(20)]  # far more than the 12 starting slots
    players.append(player("rb1", "RB", 100))  # takes the one starting RB slot
    players.append(player("rb2", "RB", 1))  # the only non-DEF competitor for the bench slot

    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=12,
        budget=200,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 1, "WR": 0, "TE": 0, "K": 0, "DEF": 1},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=1,
    )

    result = calculate_last_rostered_levels(players, config)

    assert result.by_position["DEF"].selected_count == 12  # exactly one per team, never more
    assert "rb2" in result.selected_player_ids  # the lone bench slot goes to the RB instead


def test_a_kicker_is_unreachable_here_exactly_as_it_is_for_replacement_level():
    # Real league config: K has no concrete slot and isn't part of any flex
    # (this league's own Sleeper roster_positions never mentions K at all),
    # so bench doesn't rescue it either — reachability must agree with
    # replacement level's, regardless of how many kickers or how strong
    # their projections are.
    players = [
        player("k1", "K", 250),  # would out-project every other player here
        player("qb1", "QB", 300),
    ]

    replacement = calculate_replacement_levels(players, LEAGUE_CONFIG)
    last_rostered = calculate_last_rostered_levels(players, LEAGUE_CONFIG)

    assert last_rostered.by_position["K"].reachable == replacement.by_position["K"].reachable
    assert last_rostered.by_position["K"].reachable is False
    assert last_rostered.by_position["K"].last_rostered_level is None
    assert "k1" not in last_rostered.selected_player_ids


def test_a_superflex_position_is_floored_at_its_worst_flex_peer():
    # QB has a deep pool and only one concrete slot, so pooling QBs against
    # QBs alone drives its last-rostered level far below every other
    # position's. But SUPER_FLEX takes RB/WR/TE too — nobody rosters the 5th
    # quarterback when a better running back is free for the same slot, so
    # the bar floors at the worst peer rather than at the QB pool's own tail.
    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=100,
        min_bid=1,
        starting_slots={"QB": 1, "RB": 1, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 1},
        bench_slots=1,
    )
    players = [
        player("qb1", "QB", 300),
        player("qb2", "QB", 280),
        player("qb3", "QB", 40),  # the QB pool's own tail, far below any RB
        player("rb1", "RB", 200),
        player("rb2", "RB", 150),
        player("rb3", "RB", 120),  # RB's own last-rostered level
    ]

    result = calculate_last_rostered_levels(players, config)

    assert result.by_position["RB"].last_rostered_level == 120  # unfloored: RB is the group minimum
    assert result.by_position["QB"].last_rostered_level == 120  # floored up from 40 to RB's level


def test_a_position_with_no_flex_slot_anywhere_is_never_floored():
    # DEF has a concrete slot but sits in no flex list, so it has no peers to
    # be measured against and keeps exactly the level the fill solved.
    players = [player("def1", "DEF", 100), player("def2", "DEF", 90)] + [
        player(f"rb{i}", "RB", 300 - i) for i in range(1, 4)
    ]
    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=100,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 1, "WR": 0, "TE": 0, "K": 0, "DEF": 1},
        flex_slots={"FLEX": 1, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=0,
    )

    result = calculate_last_rostered_levels(players, config)

    assert config.flex_peers("DEF") == []
    assert result.by_position["DEF"].last_rostered_level == 90
