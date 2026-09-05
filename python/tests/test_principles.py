from vorp.league.config import LeagueConfig
from vorp.models import Player, points_proportional, progressive_blend, starters_only
from vorp.principles import (
    LAW,
    PRINCIPLES,
    Context,
    indifferent_to_a_constant_shift,
    mid_draft_state,
    monotonic_within_position,
    run,
)


def player(player_id: str, position: str, points: float) -> Player:
    return Player(player_id=player_id, position=position, points=points)


CONFIG = LeagueConfig(
    league_id="test",
    draft_id="test",
    season=2026,
    teams=2,
    budget=100,
    min_bid=1,
    starting_slots={"QB": 1, "RB": 1, "WR": 1, "TE": 0, "K": 0, "DEF": 0},
    flex_slots={"FLEX": 1, "REC_FLEX": 0, "SUPER_FLEX": 0},
    bench_slots=1,
)


def board():
    """2 teams x 5 spots = 10 drafted, with leftovers at each position to set
    the bars.
    """
    players = []
    for pos, scores in (
        ("QB", [300, 280, 260, 240]),
        ("RB", [200, 180, 160, 140, 120]),
        ("WR", [190, 170, 150, 130, 110]),
    ):
        for i, points in enumerate(scores):
            players.append(player(f"{pos}{i + 1}", pos, points))
    return players


def context():
    players = board()
    # Market values that roughly track points, so the calibrations have
    # something sane to compare against.
    market = {p.player_id: max(1, int(p.points / 12)) for p in players}
    return Context(players=players, config=CONFIG, market=market)


def test_the_suite_has_teeth_a_model_without_a_baseline_fails():
    # points_proportional prices raw production, so shifting every projection
    # by the same amount moves its prices — which is exactly the mistake
    # having a baseline exists to prevent.
    finding = indifferent_to_a_constant_shift(points_proportional, context())

    assert not finding.passed
    assert finding.measure > 0


def test_a_baseline_model_is_indifferent_to_a_constant_shift():
    finding = indifferent_to_a_constant_shift(starters_only, context())

    assert finding.passed, finding.detail


def test_blending_the_bars_is_monotonic_at_every_weight():
    # The property the two-lens dial couldn't hold: because every player at a
    # position is measured against one blended bar, margin rises with points,
    # so price does too — at any floor weight, with no tuning.
    ctx = context()
    for w_floor in (0.0, 0.25, 0.5, 0.75, 1.0):
        finding = monotonic_within_position(progressive_blend(w_floor), ctx)
        assert finding.passed, f"w_floor={w_floor}: {finding.detail}"


def test_a_blended_model_satisfies_every_law():
    report = run(progressive_blend(), context())
    laws = [p for p in PRINCIPLES if p.kind == LAW]

    failed = [p.id for p in laws if not report.findings[p.id].passed]
    assert not failed, f"failed: {failed} — {[report.findings[p].detail for p in failed]}"


def test_mid_draft_state_takes_players_slots_and_money_off_the_board():
    ctx = context()

    sold, residual = mid_draft_state(ctx, fraction=0.5)

    assert sold, "some players should have sold"
    assert residual.roster_size < CONFIG.roster_size
    assert residual.budget < CONFIG.budget
    # Money and slots both shrink, so the model is re-solved against what's
    # actually left rather than the pre-draft board.
    assert residual.budget >= CONFIG.min_bid


def test_blending_prices_inverts_where_blending_bars_does_not():
    """The regression that retired the two-lens dial.

    Both approaches combine VORP and VOLR. The dial blended the *prices* --
    starters apportioned from one pool against replacement level, bench-only
    picks from another against the last-rostered level -- and nothing forces
    those two curves to meet at the seam. So a barely-clearing starter came
    out cheaper than a bench player sitting far above a much lower bar.

    Blending the *bars* measures both against the same number, and the
    inversion cannot happen. This test keeps the failure reproducible now
    that the dial's code is gone.
    """
    from vorp.bid_value import apportion_with_floor
    from vorp.last_rostered import calculate_last_rostered_levels
    from vorp.replacement_level import calculate_replacement_levels

    config = LeagueConfig(
        league_id="test",
        draft_id="test",
        season=2026,
        teams=1,
        budget=200,
        min_bid=1,
        starting_slots={"QB": 0, "RB": 2, "WR": 0, "TE": 0, "K": 0, "DEF": 0},
        flex_slots={"FLEX": 0, "REC_FLEX": 0, "SUPER_FLEX": 0},
        bench_slots=1,
    )
    players = [
        player("rb1", "RB", 300),  # starter, huge margin
        player("rb2", "RB", 105),  # starter, clears replacement (100) by just 5
        player("rb3", "RB", 100),  # bench-only, but 60 clear of last-rostered (40)
        player("rb4", "RB", 40),  # leftover: sets the last-rostered level
    ]
    ctx = Context(players=players, config=config, market={})

    # --- the retired approach: two pools, two bars, one dial ---------------
    replacement = calculate_replacement_levels(players, config)
    last_rostered = calculate_last_rostered_levels(players, config)
    by_id = {p.player_id: p for p in players}
    starters = set(replacement.selected_player_ids)
    bench = set(last_rostered.selected_player_ids) - starters

    bench_pool = config.teams * 60
    dial_prices = {
        **apportion_with_floor(
            config.teams * config.budget - bench_pool,
            {
                pid: by_id[pid].points
                - replacement.by_position[by_id[pid].position].replacement_level
                for pid in starters
            },
            config.min_bid,
        ),
        **apportion_with_floor(
            bench_pool,
            {
                pid: by_id[pid].points
                - last_rostered.by_position[by_id[pid].position].last_rostered_level
                for pid in bench
            },
            config.min_bid,
        ),
    }

    # The worse player costs more. This is the defect, reproduced.
    assert by_id["rb3"].points < by_id["rb2"].points
    assert dial_prices["rb3"] > dial_prices["rb2"]

    # --- what ships: one blended bar per position -------------------------
    blended = progressive_blend()(players, config)

    assert blended.prices["rb3"] <= blended.prices["rb2"]
    assert monotonic_within_position(progressive_blend(), ctx).passed
