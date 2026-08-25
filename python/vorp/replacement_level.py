"""01 · Calculating replacement level from projections.

See docs/spec/vorp/01-calculating-replacement.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .league.config import POSITIONS, LeagueConfig
from .league.teams import LeagueState
from .league.roster_fill import RosterFillPlayer, Slot, solve_optimal_fill, summarize_by_position

#: Same shape as RosterFillPlayer; aliased for readability at call sites.
ReplacementPlayer = RosterFillPlayer


@dataclass(frozen=True)
class PositionReplacement:
    #: False when the league has no slot — concrete or flex — that this
    #: position can ever fill.
    reachable: bool
    #: Points of the first player at this position left outside the
    #: selected set. None when unreachable, and also None when the pool ran
    #: out (see pool_exhausted).
    replacement_level: Optional[float]
    #: How many players at this position cleared the bar — i.e. ended up in
    #: the selected set, across concrete slots and every flex claim
    #: combined. The "edge of replacement" is the (selected_count + 1)-th
    #: player at this position on the ranked board.
    selected_count: int
    #: True when the source projections didn't list enough players at this
    #: position to fill its slots, so there's no next-best player to read
    #: the bar off. A data-coverage gap, not a real bar of zero.
    pool_exhausted: bool = False


@dataclass(frozen=True)
class ReplacementResult:
    by_position: Dict[str, PositionReplacement]
    #: Every player id the league-wide optimal fill selected into a slot.
    selected_player_ids: Set[str]


def _build_starting_slots(config: LeagueConfig) -> List[Slot]:
    """Pool every team's starting slots (concrete + flex) into one flat list
    of slot instances.

    The expansion itself lives in league.teams, so that mid-draft the same
    list can be built from what each seat has actually filled rather than
    from `count * teams` — see docs/spec/vorp/06.
    """
    return LeagueState.opening(config).starting_slots()


def calculate_replacement_levels(
    players: List[ReplacementPlayer],
    config: LeagueConfig,
    state: Optional[LeagueState] = None,
) -> ReplacementResult:
    """`state` is the live league; omit it for the pre-draft board, where
    every slot is open and the answer is the same either way.
    """
    slots = state.starting_slots() if state is not None else _build_starting_slots(config)
    selected_player_ids = solve_optimal_fill(players, slots)
    summary = summarize_by_position(players, slots, selected_player_ids, list(POSITIONS))

    by_position = {
        position: PositionReplacement(
            reachable=s.reachable,
            replacement_level=s.level_points,
            selected_count=s.selected_count,
            pool_exhausted=s.pool_exhausted,
        )
        for position, s in summary.items()
    }

    return ReplacementResult(by_position=by_position, selected_player_ids=selected_player_ids)
