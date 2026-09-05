"""03 · Turning a margin over a bar into whole dollars.

The apportionment every lens and every model shares: reserve each member's
min_bid, split the rest by margin, and land on exactly the pool. See
docs/spec/vorp/03-vorp-to-bid.md.
"""

from __future__ import annotations

from typing import Dict, List

from .league.roster_fill import RosterFillPlayer

BidPlayer = RosterFillPlayer


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
