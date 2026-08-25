"""Shared by replacement_level.py and last_rostered.py: the league-wide,
points-maximizing optimal fill they both solve, just over a different pool
of slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class RosterFillPlayer:
    player_id: str
    position: str
    points: float


@dataclass(frozen=True)
class Slot:
    id: int
    eligible_positions: Tuple[str, ...]


@dataclass(frozen=True)
class PositionFillSummary:
    reachable: bool
    level_points: Optional[float]
    selected_count: int
    #: True when every player at this position got seated, so there is no
    #: "best one who didn't make it" to read the bar off. The pool ran out
    #: before the slots did -- which means the source projections are
    #: truncated, not that the bar is genuinely zero. level_points is None
    #: in that case; callers must not treat it as 0.
    pool_exhausted: bool = False


def _try_assign(
    player: RosterFillPlayer,
    slots: Sequence[Slot],
    slot_occupant: Dict[int, RosterFillPlayer],
    visited: Set[int],
) -> bool:
    """Kuhn's algorithm: try to find an augmenting path that seats `player` in
    one of their eligible slots, bumping an existing occupant into another of
    *their* eligible slots if needed. Never evicts anyone from the selected
    set outright — only reroutes them.
    """
    for slot in slots:
        if player.position not in slot.eligible_positions:
            continue
        if slot.id in visited:
            continue
        visited.add(slot.id)

        occupant = slot_occupant.get(slot.id)
        if occupant is None or _try_assign(occupant, slots, slot_occupant, visited):
            slot_occupant[slot.id] = player
            return True
    return False


def solve_optimal_fill(players: Sequence[RosterFillPlayer], slots: Sequence[Slot]) -> Set[str]:
    """Processing players by points descending and greedily seating each one
    (via augmenting path) is optimal here because the set of simultaneously
    placeable players forms a transversal matroid — see
    docs/spec/vorp/01-calculating-replacement.md.
    """
    ordered = sorted(players, key=lambda p: (-p.points, p.player_id))

    slot_occupant: Dict[int, RosterFillPlayer] = {}
    for player in ordered:
        _try_assign(player, slots, slot_occupant, set())

    return {p.player_id for p in slot_occupant.values()}


def summarize_by_position(
    players: Sequence[RosterFillPlayer],
    slots: Sequence[Slot],
    selected_player_ids: Set[str],
    positions: Sequence[str],
) -> Dict[str, PositionFillSummary]:
    """For each position: how many players cleared the bar, and the points of
    the best one who didn't.
    """
    by_position: Dict[str, List[RosterFillPlayer]] = {position: [] for position in positions}
    for player in players:
        if player.position in by_position:
            by_position[player.position].append(player)
    for players_at_position in by_position.values():
        players_at_position.sort(key=lambda p: (-p.points, p.player_id))

    result: Dict[str, PositionFillSummary] = {}
    for position in positions:
        capacity = sum(1 for slot in slots if position in slot.eligible_positions)
        if capacity == 0:
            result[position] = PositionFillSummary(reachable=False, level_points=None, selected_count=0)
            continue
        ranked = by_position[position]
        selected_count = sum(1 for p in ranked if p.player_id in selected_player_ids)
        first_unselected = next((p for p in ranked if p.player_id not in selected_player_ids), None)
        result[position] = PositionFillSummary(
            reachable=True,
            level_points=first_unselected.points if first_unselected is not None else None,
            selected_count=selected_count,
            pool_exhausted=first_unselected is None,
        )
    return result
