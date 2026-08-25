from vorp.bid_value import (
    BidPlayer,
    _effective_bar,
    apportion_with_floor,
    calculate_bids,
    floor_pressure,
    split_budget,
)
from vorp.last_rostered import calculate_last_rostered_levels
from vorp.league_config import LEAGUE_CONFIG, LeagueConfig
from vorp.replacement_level import calculate_replacement_levels


def player(player_id: str, position: str, points: float) -> BidPlayer:
    return BidPlayer(player_id=player_id, position=position, points=points)


def test_a_starter_with_double_the_vorp_gets_double_the_pool_share():
    # No bench, so the whole (folded) pool goes to starters. rb1's VORP is
    # 80, rb2's is 40 — a 51-dollar pool divides that 2:1 ratio evenly,
    # isolating the ratio itself from any rounding remainder.
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

    result = calculate_bids(players, config, starter_budget_pct=1.0)

    assert result.bids["rb1"] - config.min_bid == 2 * (result.bids["rb2"] - config.min_bid)
    assert result.bids["rb1"] == 35  # min_bid(1) + 34 of the 51-dollar starter pool
    assert result.bids["rb2"] == 18  # min_bid(1) + 17
    assert "rb3" not in result.bids


def test_a_bench_only_pick_with_double_the_last_rostered_margin_gets_double_the_bench_share():
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
        player("rb1", "RB", 200),  # sole starter
        player("rb2", "RB", 100),  # bench-only, margin 80 over the last-rostered level
        player("rb3", "RB", 60),  # bench-only, margin 40
        player("rb4", "RB", 20),  # leftover, defines last_rostered_level = 20
    ]

    result = calculate_bids(players, config, starter_budget_pct=0.0)

    assert result.bids["rb2"] == 2 * result.bids["rb3"]
    assert result.bids["rb2"] == 60
    assert result.bids["rb3"] == 30
    assert "rb4" not in result.bids


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

    result = calculate_bids(players, config, starter_budget_pct=1.0)

    assert result.bids["rb2"] == config.min_bid


def test_a_streaming_position_never_draws_a_bench_bid():
    # A flood of backup defenses that would crush every bench alternative on
    # points still never wins a bench slot, because DEF is excluded from
    # bench eligibility. Only the one drafted defense per team gets a bid.
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

    result = calculate_bids(players, config)

    drafted_defs = [p for p in players if p.position == "DEF" and p.player_id in result.bids]
    assert len(drafted_defs) == 12  # exactly one per team, never bench depth
    assert "rb2" in result.bids  # the lone bench slot went to the RB instead


def test_a_position_absent_from_the_template_has_no_bid_at_all():
    players = [
        player("k1", "K", 250),  # would out-project everyone; still unreachable here
        player("qb1", "QB", 300),
    ]

    result = calculate_bids(players, LEAGUE_CONFIG)

    assert "k1" not in result.bids
    assert "qb1" in result.bids


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


def test_the_budget_splits_explicitly_into_a_starter_and_bench_pool():
    # 03's one explicit division: 90/10 of the WHOLE budget, taken at the
    # top -- not of some already-floor-reduced remainder.
    split = split_budget(LEAGUE_CONFIG)

    assert split.total == 2400
    assert split.starter_pool == 2160
    assert split.bench_pool == 240
    assert split.starter_pool + split.bench_pool == split.total


def test_a_starters_vorp_dollar_equals_his_bid():
    # The point of making the split explicit: VORP $ and the bid's starter
    # side are the same pool, the same members and the same weights, so
    # they must produce identical numbers. If these ever diverge, one of
    # them has started re-deriving a budget of its own.
    players = _full_fixture_board()
    config = LEAGUE_CONFIG

    replacement = calculate_replacement_levels(players, config)
    starters = replacement.selected_player_ids
    by_id = {p.player_id: p for p in players}

    split = split_budget(config)
    vorp_weights = {
        pid: by_id[pid].points
        - _effective_bar(
            replacement.by_position[by_id[pid].position].replacement_level,
            by_id[pid].position,
            players,
        )
        for pid in starters
    }
    vorp_dollars = apportion_with_floor(split.starter_pool, vorp_weights, config.min_bid)

    bids = calculate_bids(players, config).bids

    assert vorp_dollars  # guard against vacuously passing on an empty set
    for pid in starters:
        assert vorp_dollars[pid] == bids[pid], pid
    assert sum(vorp_dollars.values()) == split.starter_pool


def test_each_lens_is_monotonic_in_points_within_a_position():
    # The property the collapsed single bid failed. Pricing starters off
    # replacement level and bench picks off the last-rostered bar let a
    # worse player out-price a better one at the seam (Bryce Young $5 as
    # the last starting QB vs Cam Ward $10 as the first bench QB). Each
    # lens measures every player against ONE bar, so within a position
    # more points can never mean fewer dollars.
    players = _full_fixture_board()
    config = LEAGUE_CONFIG
    total = config.teams * config.budget

    replacement = calculate_replacement_levels(players, config)
    last_rostered = calculate_last_rostered_levels(players, config)
    by_id = {p.player_id: p for p in players}

    vorp_bars = {
        pos: s.replacement_level for pos, s in replacement.by_position.items()
    }
    volr_bars = {
        pos: s.last_rostered_level for pos, s in last_rostered.by_position.items()
    }

    for bars, population in (
        (vorp_bars, replacement.selected_player_ids),
        (volr_bars, last_rostered.selected_player_ids),
    ):
        weights = {
            pid: by_id[pid].points
            - _effective_bar(bars[by_id[pid].position], by_id[pid].position, players)
            for pid in population
        }
        dollars = apportion_with_floor(total, weights, config.min_bid)
        assert sum(dollars.values()) == total

        by_position = {}
        for pid in population:
            by_position.setdefault(by_id[pid].position, []).append(by_id[pid])
        for position, at_position in by_position.items():
            at_position.sort(key=lambda p: -p.points)
            for better, worse in zip(at_position, at_position[1:]):
                assert dollars[better.player_id] >= dollars[worse.player_id], (
                    position,
                    better.player_id,
                    worse.player_id,
                )


def test_floor_pressure_reports_how_much_of_a_pool_the_floors_eat():
    # The bench pool spread across every drafted player is mostly floor --
    # 192 x $1 out of $240. Surface that rather than letting the column
    # look like a real valuation.
    assert floor_pressure(pool=240, member_count=192, min_bid=1) == 192 / 240
    # The starter lens has plenty of room above its floors.
    assert floor_pressure(pool=2160, member_count=120, min_bid=1) == 120 / 2160
    # Never reports more than the whole pool, even when floors exceed it.
    assert floor_pressure(pool=100, member_count=500, min_bid=1) == 1.0


def test_worked_example_bids_reconcile_to_teams_times_budget():
    # 12 teams, $200 budget: the budget splits 2160/240 at the default 90%
    # starter share, each pool reserving the $1 floor for its OWN members
    # -> everything must sum to exactly teams * budget.
    players = []
    for i in range(50):
        players.append(player(f"qb{i + 1}", "QB", 1000 - i))
        players.append(player(f"rb{i + 1}", "RB", 900 - i))
        players.append(player(f"wr{i + 1}", "WR", 800 - i))
        players.append(player(f"te{i + 1}", "TE", 700 - i))
    for i in range(12):
        players.append(player(f"def{i + 1}", "DEF", 300 - i))

    result = calculate_bids(players, LEAGUE_CONFIG)

    assert len(result.bids) == LEAGUE_CONFIG.roster_size * LEAGUE_CONFIG.teams  # 192, full roster
    assert sum(result.bids.values()) == LEAGUE_CONFIG.teams * LEAGUE_CONFIG.budget  # 2400
    assert all(bid >= LEAGUE_CONFIG.min_bid for bid in result.bids.values())
