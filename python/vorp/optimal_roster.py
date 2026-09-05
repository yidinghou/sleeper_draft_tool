"""09 · The best affordable roster — see docs/spec/vorp/09-optimal-roster.md.

`08` (seat_value.py) prices one player at a time and never looks past the
man on the block. `plan_roster` is the auction's knapsack: given one seat's
remaining budget and open slots, and the board's current prices, the *set*
of players that buys the most starting-lineup points the money can still
reach.

Greedy by marginal-points-per-dollar, re-solving `08`'s lineup value against
the roster-plus-picks-so-far at every step -- never a fixed per-player
number summed up, because the value of a set is not the sum of its players'
values (a benched player scores nothing). Exactly optimal on a flat-price
board; within a tight bound of the true optimum otherwise. See the spec for
the full argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .league.roster_fill import RosterFillPlayer, assign_to_slots
from .league.teams import UNKNOWN_SEAT, LeagueState
from .seat_value import _lineup_points, _roster_of, free_agents, seat_values


@dataclass(frozen=True)
class Target:
    player_id: str
    position: str
    price: int
    #: Marginal starting-lineup points added at the moment this was chosen.
    #: ~0 for a `kind="fill"` entry, by construction.
    points_gain: float
    kind: str = "buy"  # "buy" or "fill"


@dataclass(frozen=True)
class RosterPlan:
    targets: Tuple[Target, ...]
    fills: Tuple[Target, ...] = ()
    spend: int = 0
    #: Dollars held back for slots still open after the plan -- `open_slots
    #: * min_bid`, the floor cost of eventually filling every one of them.
    reserve: int = 0
    budget_left_after: int = 0
    points_before: float = 0.0
    points_after: float = 0.0
    points_gain: float = 0.0
    #: The real players seated in the resulting best starting lineup.
    lineup_ids: Tuple[str, ...] = ()
    open_slots_after: int = 0


def _open_count(state: LeagueState, seat_id: int) -> int:
    return sum(1 for s in state.full_roster_slots() if s.seat_id == seat_id)


def _lineup_ids(
    roster: List[RosterFillPlayer], slots, replacement: Dict[str, float]
) -> Tuple[str, ...]:
    pool = list(roster) + free_agents(slots, replacement)
    seated = assign_to_slots(pool, list(slots))
    return tuple(sorted(pid for pid in seated.values() if not pid.startswith("__free__")))


def plan_roster(
    state: LeagueState,
    seat_id: int,
    pool: List[RosterFillPlayer],
    prices: Dict[str, int],
    replacement: Dict[str, float],
    *,
    exclude_positions: Iterable[str] = (),
    fill_all: bool = False,
) -> RosterPlan:
    """Greedy marginal-points-per-dollar buys for one seat.

    `pool` is the shoppable player list (unsold, priced); `prices` is the
    board price (`04`/`07`) each is available at -- a player absent from
    `prices` is never a target. `replacement` is per-position replacement
    level, imputed into every open slot exactly as `08` does.

    Returns an empty plan (no targets, no fills) for an unknown seat id or
    `UNKNOWN_SEAT` -- there is no roster template to plan against.
    """
    seat0 = next((s for s in state.seats if s.seat_id == seat_id), None)
    if seat0 is None or seat0.seat_id == UNKNOWN_SEAT:
        return RosterPlan(targets=())

    exclude: Set[str] = set(exclude_positions)
    points_by_id = {p.player_id: p.points for p in pool}
    shoppable = {p.player_id: p for p in pool if p.position not in exclude}

    slots0 = state.seat_slots(seat0, bench=False)
    points_before = _lineup_points(_roster_of(seat0, points_by_id), slots0, replacement)

    working = state
    targets: List[Target] = []

    while True:
        seat = next(s for s in working.seats if s.seat_id == seat_id)
        cap = working.max_bid(seat_id)
        if cap is None or cap < working.config.min_bid:
            break
        owned = {b.player_id for b in seat.bought}
        candidates = [
            p
            for pid, p in shoppable.items()
            if pid not in owned and pid in prices and prices[pid] <= cap
        ]
        if not candidates:
            break

        values = seat_values(working, seat_id, candidates, replacement, points_by_id)
        # argmax value/price; tie -> higher value; tie -> lower player_id
        # (a deterministic, arbitrary-but-stable pick, not a ranking claim).
        best_id = min(
            (c.player_id for c in candidates),
            key=lambda pid: (
                -(values.get(pid, 0.0) / prices[pid]) if prices[pid] > 0 else 0.0,
                -values.get(pid, 0.0),
                pid,
            ),
        )
        if values.get(best_id, 0.0) <= 0:
            break

        price = prices[best_id]
        position = shoppable[best_id].position
        targets.append(
            Target(player_id=best_id, position=position, price=price, points_gain=values[best_id])
        )
        working = working.sell(best_id, position, price, seat_id=seat_id)

    fills: List[Target] = []
    if fill_all:
        fills, working = _fill_remaining(working, seat_id, shoppable, prices, replacement)

    final_seat = next(s for s in working.seats if s.seat_id == seat_id)
    slots_after = working.seat_slots(final_seat, bench=False)
    points_after = _lineup_points(_roster_of(final_seat, points_by_id), slots_after, replacement)
    lineup_ids = _lineup_ids(_roster_of(final_seat, points_by_id), slots_after, replacement)

    spend = sum(t.price for t in targets) + sum(f.price for f in fills)
    open_after = _open_count(working, seat_id)
    reserve = open_after * state.config.min_bid

    return RosterPlan(
        targets=tuple(targets),
        fills=tuple(fills),
        spend=spend,
        reserve=reserve,
        budget_left_after=final_seat.budget_left,
        points_before=points_before,
        points_after=points_after,
        points_gain=points_after - points_before,
        lineup_ids=lineup_ids,
        open_slots_after=open_after,
    )


def _fill_remaining(
    working: LeagueState,
    seat_id: int,
    shoppable: Dict[str, RosterFillPlayer],
    prices: Dict[str, int],
    replacement: Dict[str, float],
) -> Tuple[List[Target], LeagueState]:
    """Second phase of `plan_roster` under `fill_all`: a cheap body for every
    slot still open, cheapest-first, tie-broken by margin over replacement
    (the best still-available flier, not the highest raw total) then by id.
    Each fill adds ~0 starting points by construction -- it is filling
    bench/overflow, not upgrading the lineup.
    """
    fills: List[Target] = []
    while True:
        seat = next(s for s in working.seats if s.seat_id == seat_id)
        cap = working.max_bid(seat_id)
        if cap is None or cap < working.config.min_bid:
            break
        owned = {b.player_id for b in seat.bought}
        candidates = [
            p
            for pid, p in shoppable.items()
            if pid not in owned and pid in prices and prices[pid] <= cap
        ]
        if not candidates:
            break

        def fill_key(p: RosterFillPlayer):
            margin = p.points - replacement.get(p.position, p.points)
            return (prices[p.player_id], -margin, p.player_id)

        chosen = min(candidates, key=fill_key)
        price = prices[chosen.player_id]
        fills.append(
            Target(player_id=chosen.player_id, position=chosen.position, price=price, points_gain=0.0, kind="fill")
        )
        working = working.sell(chosen.player_id, chosen.position, price, seat_id=seat_id)

    return fills, working
