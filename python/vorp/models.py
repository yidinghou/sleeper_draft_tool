"""Candidate valuation models, all behind one interface, so the principles
in `principles.py` can be run against any of them.

A model is a function `(players, config) -> Valuation`. That's the whole
contract. What it does inside -- an optimal fill, a fixed positional rank,
a coin flip -- is its own business; the principles judge the output.

The point of this module is that "which model is better" stops being an
argument and becomes a table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from .bid_value import apportion_with_floor, floor_pressure, _effective_bar
from .last_rostered import calculate_last_rostered_levels
from .league_config import FLEX_ELIGIBILITY, POSITIONS, STREAMING_POSITIONS, LeagueConfig
from .replacement_level import calculate_replacement_levels
from .roster_fill import RosterFillPlayer

Player = RosterFillPlayer


@dataclass(frozen=True)
class Valuation:
    """What every model has to produce, and all the principles get to see.

    `prices` covers exactly the players this model says will be drafted. A
    player absent from it is unpriced -- which is a claim ("nobody spends a
    dollar here"), not a price of zero. `bench_order` is separate on
    purpose: ranking who to take with a floor bid is a different question
    from what to pay, and a model is allowed to answer one without the
    other.
    """

    name: str
    prices: Dict[str, int]
    starters: Set[str]
    bench: Set[str]
    #: player_ids at the bench, best first. Empty when the model doesn't rank.
    bench_order: List[str] = field(default_factory=list)
    #: Free-form diagnostics a principle may read, e.g. floor pressure.
    diagnostics: Dict[str, float] = field(default_factory=dict)


Model = Callable[[List[Player], LeagueConfig], Valuation]


def _bars(players: List[Player], config: LeagueConfig, state=None):
    """Both solved bars, plus who each fill selected. Shared by the models
    that use the optimal fill; a model is free to ignore it.

    `state` is the live league (docs/spec/vorp/06); None means the pre-draft
    board, where every slot is open.
    """
    replacement = calculate_replacement_levels(players, config, state)
    last_rostered = calculate_last_rostered_levels(players, config, state)
    vorp_bar = {
        pos: _effective_bar(s.replacement_level, pos, players)
        for pos, s in replacement.by_position.items()
        if s.reachable
    }
    volr_bar = {
        pos: _effective_bar(s.last_rostered_level, pos, players)
        for pos, s in last_rostered.by_position.items()
        if s.reachable
    }
    return replacement, last_rostered, vorp_bar, volr_bar


# --------------------------------------------------------------------------
# Model A -- price the starters, rank the bench
# --------------------------------------------------------------------------


def starters_only(players: List[Player], config: LeagueConfig) -> Valuation:
    """The simplification: bench picks cost min_bid, full stop. Every dollar
    above the bench's floors is apportioned among starters by VORP.

    The bench still gets an *order* -- VOLR margin in raw points -- because
    which flier to take is a real question. It just isn't a pricing one, and
    answering it in dollars was what dragged the seam in.
    """
    replacement, last_rostered, vorp_bar, volr_bar = _bars(players, config)
    by_id = {p.player_id: p for p in players}
    starters = set(replacement.selected_player_ids)
    bench = set(last_rostered.selected_player_ids) - starters

    bench_pool = len(bench) * config.min_bid
    starter_pool = config.teams * config.budget - bench_pool

    vorp_weights = {
        pid: by_id[pid].points - vorp_bar[by_id[pid].position] for pid in starters
    }
    prices = {
        **apportion_with_floor(starter_pool, vorp_weights, config.min_bid),
        **{pid: config.min_bid for pid in bench},
    }
    return Valuation(
        name="starters priced, bench ranked",
        prices=prices,
        starters=starters,
        bench=bench,
        bench_order=sorted(
            bench, key=lambda pid: -(by_id[pid].points - volr_bar[by_id[pid].position])
        ),
        diagnostics={
            "floor_pressure_starters": floor_pressure(
                starter_pool, len(vorp_weights), config.min_bid
            ),
            "floor_pressure_bench": 1.0,  # by construction: the bench is all floor
        },
    )


# --------------------------------------------------------------------------
# Model B -- fixed flex allocation, no optimal fill
# --------------------------------------------------------------------------

#: Which position each flex type is assumed to go to, instead of solving for
#: it. SUPER_FLEX to QB is the one that carries real weight (a QB outscores
#: any flex-eligible skill player in this scoring), and it's also the one a
#: human would never get wrong. The rest lean receiver, which is where the
#: solve put them too.
ASSUMED_FLEX = {"SUPER_FLEX": "QB", "REC_FLEX": "WR", "FLEX": "WR"}


def fixed_flex(players: List[Player], config: LeagueConfig) -> Valuation:
    """Same shape as `starters_only`, but the bar is the Nth-best player at
    each position with N read off a fixed flex assumption -- no optimal fill
    anywhere. The cheap model, here to be measured against the expensive one
    rather than dismissed.
    """
    by_position: Dict[str, List[Player]] = {}
    for p in players:
        by_position.setdefault(p.position, []).append(p)
    for group in by_position.values():
        group.sort(key=lambda p: (-p.points, p.player_id))

    starting_counts = {
        pos: config.starting_slots.get(pos, 0) * config.teams for pos in POSITIONS
    }
    for flex, per_team in config.flex_slots.items():
        if per_team:
            starting_counts[ASSUMED_FLEX[flex]] += per_team * config.teams

    bench_positions = [
        pos
        for pos in config.draftable_positions()
        if pos not in STREAMING_POSITIONS
    ]

    starters: Set[str] = set()
    vorp_weights: Dict[str, float] = {}
    for pos, count in starting_counts.items():
        group = by_position.get(pos, [])
        if not count or not group:
            continue
        chosen = group[:count]
        bar = group[count].points if len(group) > count else min(p.points for p in group)
        for p in chosen:
            starters.add(p.player_id)
            vorp_weights[p.player_id] = p.points - bar

    # Bench: the next best players at bench-eligible positions, pooled and
    # taken in points order until the bench slots run out.
    taken = set(starters)
    leftovers = sorted(
        (p for pos in bench_positions for p in by_position.get(pos, []) if p.player_id not in taken),
        key=lambda p: (-p.points, p.player_id),
    )
    bench_slots = config.bench_slots * config.teams
    bench_players = leftovers[:bench_slots]
    bench = {p.player_id for p in bench_players}

    bench_pool = len(bench) * config.min_bid
    starter_pool = config.teams * config.budget - bench_pool
    prices = {
        **apportion_with_floor(starter_pool, vorp_weights, config.min_bid),
        **{pid: config.min_bid for pid in bench},
    }
    return Valuation(
        name="fixed flex, no solve",
        prices=prices,
        starters=starters,
        bench=bench,
        bench_order=[p.player_id for p in bench_players],
        diagnostics={
            "floor_pressure_starters": floor_pressure(
                starter_pool, len(vorp_weights), config.min_bid
            ),
            "floor_pressure_bench": 1.0,
        },
    )


# --------------------------------------------------------------------------
# Model C -- blend the BARS, not the prices
# --------------------------------------------------------------------------


#: Where the ramp starts: the top `FULL_WEIGHT_SHARE` of starters at a
#: position are never blended at all. Part of the model's shape, not a knob
#: -- `w_floor` is the one dial a human sets, and adding a second one only
#: gives two ways to say the same thing. See docs/spec/vorp/04.
FULL_WEIGHT_SHARE = 0.75


def full_weight_points(
    starters: Set[str], by_id: Dict[str, Player], position: str
) -> Optional[float]:
    """Points of the starter sitting `FULL_WEIGHT_SHARE` down the ranking at
    this position -- the point above which nobody is blended at all.
    """
    ranked = sorted(
        (by_id[pid].points for pid in starters if by_id[pid].position == position),
        reverse=True,
    )
    if not ranked:
        return None
    return ranked[min(int(len(ranked) * FULL_WEIGHT_SHARE), len(ranked) - 1)]


def blend_weights(players: List[Player], config: LeagueConfig, state=None):
    """The per-position ramp: where it starts and where it ends.

    Independent of `w_floor` -- the dial changes how far the bar slides
    inside this band, never where the band is. Returned separately from the
    pricing so `principles.ramp_slope_is_safe` can check the steepness
    without re-deriving it.
    """
    replacement, last_rostered, vorp_bar, volr_bar = _bars(players, config, state)
    by_id = {p.player_id: p for p in players}
    starters = set(replacement.selected_player_ids)

    ramps = {}
    for position, bottom in volr_bar.items():
        # Mid-draft a position can run out of starting slots league-wide while
        # players and bench slots remain. It has no replacement level then, and
        # that's the honest answer: it has become a pure bench position, priced
        # entirely off the last-rostered bar. Collapsing the ramp onto `bottom`
        # says exactly that, rather than dropping the position and pricing
        # everyone there at nothing.
        top_bar = vorp_bar.get(position, bottom)
        full_weight = full_weight_points(starters, by_id, position)
        ramps[position] = {
            "top": full_weight if full_weight is not None else top_bar,
            "bottom": bottom,
            "replacement": top_bar,
            "last_rostered": bottom,
        }
    return replacement, last_rostered, vorp_bar, volr_bar, ramps


def progressive_blend(w_floor: float = 0.5) -> Model:
    """The shipped model: blend the BARS, and blend them only where the
    starter/bench distinction is genuinely ambiguous.

    **`w_floor` is the only dial, and a human sets it.** Everything else
    about the shape -- where the band starts, that the ramp is linear in
    points, that the top of the board is never blended -- is fixed, so
    there is exactly one number to argue about and one slider to move.

    `03`'s bid broke because it measured different players against different
    bars -- starters against replacement level, bench against the
    last-rostered level -- and nothing forces those two curves to meet at the
    seam. Blending the bars removes that failure mode by construction, and
    ramping the blend keeps the top of the board undiluted:

        w(p)   = w_floor + (1 - w_floor) * t,  t ramping 0 -> 1 in POINTS
                 from the last-rostered level up to the full-weight point
        bar(p) = w(p) * replacement_level + (1 - w(p)) * last_rostered_level
        margin = max(0, points - bar(p))

    The top `FULL_WEIGHT_SHARE` of starters at a position sit above the ramp
    entirely: w = 1, measured against replacement level, exactly as a starter
    should be. Below them the bar slides toward the last-rostered level, so a
    marginal starter and a strong bench pick are priced on the same
    continuum instead of falling off a cliff between two lenses.

    **The ramp is linear in points, not in rank**, and that is load-bearing.
    Price stays monotonic iff `(R - L) * dw/dpoints <= 1`; ramping in points
    makes that slope a constant the `ramp-slope` law can check, while ramping
    by rank makes it explode wherever players bunch tightly in points --
    which is exactly the bottom of every position's board.

    `w_floor = 1.0` collapses to pure VORP; `w_floor = 0.0` blends all the
    way to the last-rostered level at the bottom.
    """

    def model(players: List[Player], config: LeagueConfig, state=None) -> Valuation:
        replacement, last_rostered, vorp_bar, volr_bar, ramps = blend_weights(
            players, config, state
        )
        by_id = {p.player_id: p for p in players}
        starters = set(replacement.selected_player_ids)
        drafted = set(last_rostered.selected_player_ids)

        weights = {}
        for pid in drafted:
            player = by_id[pid]
            ramp = ramps.get(player.position)
            if ramp is None:
                continue
            top, bottom = ramp["top"], ramp["bottom"]
            if player.points >= top or top <= bottom:
                t = 1.0
            elif player.points <= bottom:
                t = 0.0
            else:
                t = (player.points - bottom) / (top - bottom)
            w = w_floor + (1 - w_floor) * t
            bar = w * ramp["replacement"] + (1 - w) * ramp["last_rostered"]
            weights[pid] = max(0.0, player.points - bar)

        # The money actually left in the room. Pre-draft this is exactly
        # teams * budget; mid-draft it is what the seats still hold.
        pool = state.pool() if state is not None else config.teams * config.budget
        prices = apportion_with_floor(pool, weights, config.min_bid)
        return Valuation(
            name=f"progressive blend (floor {w_floor:.2f})",
            prices=prices,
            starters=starters,
            bench=drafted - starters,
            bench_order=sorted(
                drafted - starters,
                key=lambda pid: -(by_id[pid].points - volr_bar[by_id[pid].position]),
            ),
            diagnostics={
                "floor_pressure_starters": floor_pressure(
                    pool, len(weights), config.min_bid
                ),
                "floor_pressure_bench": floor_pressure(
                    pool, len(weights), config.min_bid
                ),
            },
        )

    return model


# --------------------------------------------------------------------------
# Model D -- deliberately wrong, to prove the principles have teeth
# --------------------------------------------------------------------------


def points_proportional(players: List[Player], config: LeagueConfig) -> Valuation:
    """Split the budget proportional to raw projected points, no baseline at
    all. A strawman: it should fail the principles that matter, and a suite
    that passes it isn't testing anything.
    """
    _, last_rostered, _, _ = _bars(players, config)
    drafted = set(last_rostered.selected_player_ids)
    replacement, *_ = _bars(players, config)
    starters = set(replacement.selected_player_ids)
    by_id = {p.player_id: p for p in players}

    weights = {pid: by_id[pid].points for pid in drafted}
    prices = apportion_with_floor(config.teams * config.budget, weights, config.min_bid)
    return Valuation(
        name="points-proportional (strawman)",
        prices=prices,
        starters=starters,
        bench=drafted - starters,
        bench_order=sorted(drafted - starters, key=lambda pid: -by_id[pid].points),
    )


#: Where the one dial ships set. 0.5 is where the ramp's starter/bench split
#: and market error both land best -- see docs/spec/vorp/04.
DEFAULT_W_FLOOR = 0.5

REGISTRY: Dict[str, Model] = {
    "shipped": progressive_blend(DEFAULT_W_FLOOR),
    "ramp-0.75": progressive_blend(0.75),
    "ramp-0.25": progressive_blend(0.25),
    "ramp-0.00": progressive_blend(0.00),
    "pure-vorp": progressive_blend(1.00),
    "starters-only": starters_only,
    "fixed-flex": fixed_flex,
    "strawman": points_proportional,
}
