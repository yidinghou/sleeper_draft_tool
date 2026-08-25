"""02 · Value over last rostered.

See docs/spec/vorp/02-value-over-last-rostered.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .league.config import POSITIONS, LeagueConfig
from .league.teams import LeagueState
from .league.roster_fill import RosterFillPlayer, Slot, solve_optimal_fill, summarize_by_position

LastRosteredPlayer = RosterFillPlayer


@dataclass(frozen=True)
class PositionLastRostered:
    #: Always equal to replacement level's reachable flag for the same
    #: position: bench adds depth, never reachability. A position absent
    #: from the league's template entirely (no concrete slot, no flex) is
    #: unreachable here exactly as it is for replacement level.
    reachable: bool
    #: Points of the first player at this position left outside the
    #: fully-rostered selected set. None when unreachable, and also None
    #: when the pool ran out (see pool_exhausted).
    last_rostered_level: Optional[float]
    #: How many players at this position actually got drafted, starting or
    #: bench, in the optimal fill.
    selected_count: int
    #: True when every player at this position got rostered, so there's no
    #: next-best player to read the bar off. Happens when the source
    #: projections cover fewer players than the league has slots for — a
    #: data-coverage gap, not a real bar of zero.
    pool_exhausted: bool = False


@dataclass(frozen=True)
class LastRosteredResult:
    by_position: Dict[str, PositionLastRostered]
    #: Every player id the full-roster (starting + bench) optimal fill selected.
    selected_player_ids: Set[str]


def _build_full_roster_slots(config: LeagueConfig) -> List[Slot]:
    """Pool every team's roster slot — concrete, flex, AND bench — into one
    flat list. Unlike a flex slot, a bench slot doesn't have to match one
    specific slot's eligibility list — but it's still restricted to
    positions this league's template plays *somewhere* (own slot or any
    flex). A position with no footprint in the template at all (K, here)
    stays out of the pool entirely, bench included — see
    LeagueConfig.draftable_positions.

    STREAMING_POSITIONS is a second, narrower exclusion from bench
    eligibility specifically: DEF has a real starting slot and is fully
    draftable, but real managers stream it off waivers rather than bench a
    second one, so it's excluded from the bench pool even though it's
    otherwise draftable.

    The expansion itself lives in league.teams, which owns the bench
    eligibility rule described above — see docs/spec/league/03-seats-and-sales.md.
    """
    return LeagueState.opening(config).full_roster_slots()


def _flex_peer_floor(
    levels: Dict[str, Optional[float]], config: LeagueConfig
) -> Dict[str, Optional[float]]:
    """Raise any position's last-rostered level to the worst level among the
    positions it competes with for a flex slot.

    The solve will happily say the 50th-best quarterback is the last rostered
    one, because it is pooling QBs against QBs. Nobody actually drafts him: a
    superflex slot takes RB, WR and TE too, and the worst rostered receiver
    is far better. A bar below every alternative for the same slot isn't a
    bar anyone can be measured against.

    Floors are read off the *raw* solved levels in a single pass, so only the
    outlier moves -- every other position in the group already sits above the
    group minimum, and lifting the outlier can't drag anyone else up. A
    position with no flex slot anywhere (DEF here) has no peers and is left
    exactly as solved.
    """
    floored: Dict[str, Optional[float]] = {}
    for position, level in levels.items():
        peers = [
            levels[peer]
            for peer in config.flex_peers(position)
            if levels.get(peer) is not None
        ]
        if level is None or not peers:
            floored[position] = level
        else:
            floored[position] = max(level, min(peers))
    return floored


def calculate_last_rostered_levels(
    players: List[LastRosteredPlayer],
    config: LeagueConfig,
    state: Optional[LeagueState] = None,
) -> LastRosteredResult:
    """`state` is the live league; omit it for the pre-draft board, where
    every slot is open and the answer is the same either way.
    """
    slots = (
        state.full_roster_slots() if state is not None else _build_full_roster_slots(config)
    )
    selected_player_ids = solve_optimal_fill(players, slots)
    summary = summarize_by_position(players, slots, selected_player_ids, list(POSITIONS))

    levels = _flex_peer_floor(
        {position: s.level_points for position, s in summary.items()}, config
    )

    by_position = {
        position: PositionLastRostered(
            reachable=s.reachable,
            last_rostered_level=levels[position],
            selected_count=s.selected_count,
            pool_exhausted=s.pool_exhausted,
        )
        for position, s in summary.items()
    }

    return LastRosteredResult(by_position=by_position, selected_player_ids=selected_player_ids)
