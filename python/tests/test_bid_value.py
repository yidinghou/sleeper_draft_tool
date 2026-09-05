from typing import Dict, List

from vorp.bid_value import (
    BidPlayer,
    _effective_bar,
    apportion_with_floor,
    floor_pressure,
)
from vorp.last_rostered import calculate_last_rostered_levels
from vorp.league_config import LEAGUE_CONFIG, LeagueConfig
from vorp.replacement_level import calculate_replacement_levels


def player(player_id: str, position: str, points: float) -> BidPlayer:
    return BidPlayer(player_id=player_id, position=position, points=points)


def lens_dollars(
    players: List[BidPlayer], config: LeagueConfig, lens: str
) -> Dict[str, int]:
    """One of 03's two lenses, exactly as `scripts/bid_value.py` builds it:
    the WHOLE budget apportioned by margin over that lens's single bar,
    among that lens's own population.

    The two lenses stay separate on purpose -- see 03. Combining them into
    one dollar figure is 04's job, and it does it by blending the *bars*.
    """
    total = config.teams * config.budget
    by_id = {p.player_id: p for p in players}

    if lens == "vorp":
        solved = calculate_replacement_levels(players, config)
        population = solved.selected_player_ids
        bars = {pos: s.replacement_level for pos, s in solved.by_position.items()}
    else:
        solved = calculate_last_rostered_levels(players, config)
        population = solved.selected_player_ids
        bars = {pos: s.last_rostered_level for pos, s in solved.by_position.items()}

    weights = {
        pid: by_id[pid].points
        - _effective_bar(bars[by_id[pid].position], by_id[pid].position, players)
        for pid in population
    }
    return apportion_with_floor(total, weights, config.min_bid)


def test_a_starter_with_double_the_vorp_gets_double_the_pool_share():
    # rb1's VORP is 80, rb2's is 40 — a 51-dollar pool above the floors
    # divides that 2:1 ratio evenly, isolating the ratio itself from any
    # rounding remainder.
    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=53,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 2, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=0,
    )
    players = [
        player("rb1", "RB", 100),  # VORP 80
        player("rb2", "RB", 60),  # VORP 40
        player("rb3", "RB", 20),  # leftover, defines replacement_level = 20
    ]

    dollars = lens_dollars(players, config, "vorp")

    assert dollars["rb1"] - config.min_bid == 2 * (dollars["rb2"] - config.min_bid)
    assert dollars["rb1"] == 35  # min_bid(1) + 34 of the 51-dollar pool
    assert dollars["rb2"] == 18  # min_bid(1) + 17
    assert "rb3" not in dollars


def test_a_bench_only_pick_with_double_the_last_rostered_margin_gets_double_the_share():
    # The VOLR lens prices everyone the full-roster fill selects, bench
    # included, against the one last-rostered bar.
    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=90,
        min_bid=0,
        starting_slots={"QB": 0, "RB": 1, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=2,
    )
    players = [
        player("rb1", "RB", 200),  # starter, margin 180 over last-rostered (20)
        player("rb2", "RB", 100),  # bench-only, margin 80
        player("rb3", "RB", 60),  # bench-only, margin 40
        player("rb4", "RB", 20),  # leftover: sets last_rostered_level = 20
    ]

    dollars = lens_dollars(players, config, "volr")

    assert dollars["rb2"] == 2 * dollars["rb3"]
    assert "rb4" not in dollars
    assert sum(dollars.values()) == config.teams * config.budget


def test_a_player_at_exactly_zero_margin_still_gets_min_bid():
    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=52,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 2, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=0,
    )
    players = [
        player("rb1", "RB", 100),
        player("rb2", "RB", 50),  # ties rb3 on points; selected into the 2nd slot
        player("rb3", "RB", 50),  # leftover; defines replacement_level = 50, so rb2's VORP is 0
    ]

    dollars = lens_dollars(players, config, "vorp")

    assert dollars["rb2"] == config.min_bid


def test_a_streaming_position_never_draws_a_bench_dollar():
    # A flood of backup defenses that would crush every bench alternative on
    # points still never wins a bench slot, because DEF is excluded from
    # bench eligibility. Only the one drafted defense per team is priced.
    players = [player(f"def{i + 1}", "DEF", 500 - i) for i in range(20)]
    players.append(player("rb1", "RB", 100))
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

    dollars = lens_dollars(players, config, "volr")

    drafted_defs = [p for p in players if p.position == "DEF" and p.player_id in dollars]
    assert len(drafted_defs) == 12  # exactly one per team, never bench depth
    assert "rb2" in dollars  # the lone bench slot went to the RB instead


def test_a_position_absent_from_the_template_has_no_figure_at_all():
    players = [
        player("k1", "K", 250),  # would out-project everyone; still unreachable here
        player("qb1", "QB", 300),
    ]

    dollars = lens_dollars(players, LEAGUE_CONFIG, "volr")

    assert "k1" not in dollars
    assert "qb1" in dollars


def _full_fixture_board():
    players = []
    for i in range(50):
        players.append(player(f"qb{i + 1}", "QB", 1000 - i))
        players.append(player(f"rb{i + 1}", "RB", 900 - i))
        players.append(player(f"wr{i + 1}", "WR", 800 - i))
        players.append(player(f"te{i + 1}", "TE", 700 - i))
    for i in range(12):
        players.append(player(f"def{i + 1}", "DEF", 300 - i))
    return players


def test_each_lens_independently_reconciles_to_teams_times_budget():
    # Neither lens is "the price," so neither gets a share of the budget:
    # each spends the whole thing on its own thinking, which is what puts
    # the two columns on one scale a human can weigh. See 03.
    players = _full_fixture_board()
    total = LEAGUE_CONFIG.teams * LEAGUE_CONFIG.budget

    volr = lens_dollars(players, LEAGUE_CONFIG, "volr")
    vorp = lens_dollars(players, LEAGUE_CONFIG, "vorp")

    assert len(volr) == LEAGUE_CONFIG.roster_size * LEAGUE_CONFIG.teams  # 192, full roster
    assert sum(volr.values()) == total
    assert sum(vorp.values()) == total
    assert all(d >= LEAGUE_CONFIG.min_bid for d in volr.values())
    # The VORP lens prices only starters, so its population is the smaller one.
    assert set(vorp) < set(volr)


def test_each_lens_is_monotonic_in_points_within_a_position():
    # The property the collapsed single bid failed. Pricing starters off
    # replacement level and bench picks off the last-rostered bar let a
    # worse player out-price a better one at the seam (Bryce Young $5 as
    # the last starting QB vs Cam Ward $10 as the first bench QB). Each
    # lens measures every player against ONE bar, so within a position
    # more points can never mean fewer dollars.
    players = _full_fixture_board()
    by_id = {p.player_id: p for p in players}

    for lens in ("vorp", "volr"):
        dollars = lens_dollars(players, LEAGUE_CONFIG, lens)

        by_position: Dict[str, list] = {}
        for pid in dollars:
            by_position.setdefault(by_id[pid].position, []).append(by_id[pid])
        for position, at_position in by_position.items():
            at_position.sort(key=lambda p: -p.points)
            for better, worse in zip(at_position, at_position[1:]):
                assert dollars[better.player_id] >= dollars[worse.player_id], (
                    lens,
                    position,
                    better.player_id,
                    worse.player_id,
                )


def test_floor_pressure_reports_how_much_of_a_pool_the_floors_eat():
    # 192 players at $1 out of a $240 pool is mostly floor -- surface that
    # rather than letting the column look like a real valuation.
    assert floor_pressure(pool=240, member_count=192, min_bid=1) == 192 / 240
    # The same 120 starters against the whole budget have plenty of room.
    assert floor_pressure(pool=2160, member_count=120, min_bid=1) == 120 / 2160
    # Never reports more than the whole pool, even when floors exceed it.
    assert floor_pressure(pool=100, member_count=500, min_bid=1) == 1.0
