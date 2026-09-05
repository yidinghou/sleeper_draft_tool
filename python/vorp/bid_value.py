"""03 · Translating VORP into a bid amount.

See docs/spec/vorp/03-vorp-to-bid.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .last_rostered import calculate_last_rostered_levels
from .league_config import LeagueConfig
from .replacement_level import calculate_replacement_levels
from .roster_fill import RosterFillPlayer

BidPlayer = RosterFillPlayer

#: Default share of the WHOLE budget reserved for starters, roughly
#: matching how a real auction's money splits. A tunable knob on the
#: valuation function, not a structural fact about any league.
DEFAULT_STARTER_BUDGET_PCT = 0.90


@dataclass(frozen=True)
class BudgetSplit:
    """The one explicit division of `teams * budget`, per 03's spec.

    Every dollar figure in this module draws on `starter_pool` or
    `bench_pool` -- nothing re-derives a budget of its own. The min_bid
    floor is reserved *inside* whichever pool is paying, from that pool's
    own members, not off the top of the combined budget.
    """

    total: int
    starter_pool: int
    bench_pool: int


def split_budget(
    config: LeagueConfig, starter_budget_pct: float = DEFAULT_STARTER_BUDGET_PCT
) -> BudgetSplit:
    total = config.teams * config.budget
    starter_pool = round(total * starter_budget_pct)
    return BudgetSplit(total=total, starter_pool=starter_pool, bench_pool=total - starter_pool)


def floor_pressure(pool: int, member_count: int, min_bid: int) -> float:
    """What share of `pool` the min_bid floors eat. Near 1.0 means the
    lens is almost entirely floor and its ordering barely reflects margin
    -- surface it rather than letting the numbers look like a valuation.
    """
    if pool <= 0:
        return 1.0
    return min(1.0, (member_count * min_bid) / pool)


def apportion_with_floor(pool: int, weights: Dict[str, float], min_bid: int) -> Dict[str, int]:
    """Reserve `min_bid` for each member out of `pool`, split the rest by
    weight, then add the floor back. Shares sum to exactly `pool`.
    """
    floor_total = len(weights) * min_bid
    shares = apportion(max(0, pool - floor_total), weights)
    return {player_id: min_bid + share for player_id, share in shares.items()}


@dataclass(frozen=True)
class BidResult:
    #: player_id -> whole-dollar bid, >= config.min_bid. Only players in
    #: 02's full-roster selected set appear here; everyone else is
    #: unreachable, not $0.
    bids: Dict[str, int]


def apportion(pool: int, weights: Dict[str, float]) -> Dict[str, int]:
    """Split `pool` whole dollars across `weights` proportionally, using
    largest-remainder (Hamilton) apportionment so the shares always sum to
    exactly `pool` regardless of rounding.
    """
    if pool <= 0 or not weights:
        return {player_id: 0 for player_id in weights}

    total_weight = sum(weights.values())
    if total_weight <= 0:
        # No margin to split on — divide the pool evenly instead of by zero.
        base = pool // len(weights)
        shares = {player_id: base for player_id in weights}
        remainder = pool - base * len(weights)
        for player_id in sorted(weights)[:remainder]:
            shares[player_id] += 1
        return shares

    raw = {player_id: pool * weight / total_weight for player_id, weight in weights.items()}
    shares = {player_id: int(value) for player_id, value in raw.items()}
    remainder = pool - sum(shares.values())

    ranked = sorted(weights, key=lambda pid: (-(raw[pid] - shares[pid]), pid))
    for player_id in ranked[:remainder]:
        shares[player_id] += 1

    return shares


def _effective_bar(level: float | None, position: str, players: List[BidPlayer]) -> float:
    """The bar to measure a player's margin against.

    Normally that's the level the fill solved for. But when a position's
    pool is exhausted -- the source projections list fewer players there
    than the league has slots for -- there's no next-best player to read
    the bar off and the level comes back None. The true bar sits somewhere
    below the worst player in the pool; the worst player himself is the
    tightest bound we can actually justify, so use him. That keeps margins
    finite and ordered instead of pricing everyone at the position against
    a bar of zero, which would inflate the whole group.
    """
    if level is not None:
        return level
    at_position = [p.points for p in players if p.position == position]
    return min(at_position) if at_position else 0.0


def calculate_bids(
    players: List[BidPlayer],
    config: LeagueConfig,
    starter_budget_pct: float = DEFAULT_STARTER_BUDGET_PCT,
) -> BidResult:
    replacement = calculate_replacement_levels(players, config)
    last_rostered = calculate_last_rostered_levels(players, config)

    by_id = {p.player_id: p for p in players}
    starters = replacement.selected_player_ids
    bench_only = last_rostered.selected_player_ids - starters

    split = split_budget(config, starter_budget_pct)
    starter_pool, bench_pool = split.starter_pool, split.bench_pool

    # Nobody to spend the bench pool on: fold it into the starter pool so
    # the bids still reconcile to the whole budget.
    if not bench_only:
        starter_pool += bench_pool
        bench_pool = 0

    starter_weights = {
        player_id: by_id[player_id].points
        - _effective_bar(
            replacement.by_position[by_id[player_id].position].replacement_level,
            by_id[player_id].position,
            players,
        )
        for player_id in starters
    }
    bench_weights = {
        player_id: by_id[player_id].points
        - _effective_bar(
            last_rostered.by_position[by_id[player_id].position].last_rostered_level,
            by_id[player_id].position,
            players,
        )
        for player_id in bench_only
    }

    # Each pool reserves its own members' floors, per 03's explicit rule.
    bids = {
        **apportion_with_floor(starter_pool, starter_weights, config.min_bid),
        **apportion_with_floor(bench_pool, bench_weights, config.min_bid),
    }

    return BidResult(bids=bids)
