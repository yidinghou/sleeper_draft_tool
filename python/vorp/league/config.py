"""League settings for the 2026 draft, read from Sleeper:
GET /draft/1372724723120631808 -> .settings

Kept as a static config rather than fetched live because these rules are
frozen once the draft is created and shared by every seat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

#: Positions real managers stream off the waiver wire week to week rather
#: than draft bench depth for. DEF is high-variance and matchup-dependent —
#: nobody actually spends a bench slot on a second defense, even though a
#: defense has a real starting slot and is fully draftable. Excluded from
#: bench eligibility in last_rostered.py; still counted normally everywhere
#: else (its own concrete slot, replacement level).
STREAMING_POSITIONS = ("DEF",)

#: Which positions each flex slot can hold.
FLEX_ELIGIBILITY: Dict[str, List[str]] = {
    "FLEX": ["RB", "WR", "TE"],
    "REC_FLEX": ["WR", "TE"],
    "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
}


@dataclass(frozen=True)
class LeagueConfig:
    league_id: str
    draft_id: str
    season: int
    teams: int
    budget: int
    min_bid: int
    starting_slots: Dict[str, int]  # concrete (non-flex) starting slots, by position
    flex_slots: Dict[str, int]  # flex starting slots, by flex type
    bench_slots: int
    #: Positions this league plays, when that can't be derived from the slot
    #: counts above. None means derive it, which is right pre-draft.
    #:
    #: Mid-draft it is not: a residual config models consumed slots by
    #: zeroing them, and a position whose starting slots are all spoken for
    #: would then look like a position the league never plays at all --
    #: dropping it from bench eligibility and pricing every remaining player
    #: there at nothing. Which positions a league plays is a property of its
    #: template and doesn't change as the draft runs, so a residual config
    #: carries the original list forward here.
    plays_positions: Optional[Tuple[str, ...]] = None

    @property
    def roster_size(self) -> int:
        """Total roster size: starting slots (concrete + flex) plus bench."""
        concrete = sum(self.starting_slots.values())
        flex = sum(self.flex_slots.values())
        return concrete + flex + self.bench_slots

    def flex_peers(self, position: str) -> List[str]:
        """Every *other* position that competes with `position` for a flex
        slot somewhere in this template.

        Union across flex types, not one specific slot: a position competes
        with everyone it could ever be passed over for. In this league
        SUPER_FLEX makes QB, RB, WR and TE all peers of each other; DEF has
        no flex slot anywhere, so it has no peers and no peer-derived floor.
        """
        peers = set()
        for flex, count in self.flex_slots.items():
            eligible = FLEX_ELIGIBILITY[flex]
            if count > 0 and position in eligible:
                peers.update(eligible)
        peers.discard(position)
        return [p for p in POSITIONS if p in peers]

    def draftable_positions(self) -> List[str]:
        """Positions this league's roster template plays anywhere — its own
        concrete slot, or a flex slot that accepts it.

        A position absent from both isn't part of this league's draftable
        pool at all. This league's own `roster_positions` from Sleeper never
        mentions K anywhere — no concrete slot, not in FLEX/REC_FLEX/
        SUPER_FLEX — so kickers are never draftable here, full stop. A bench
        slot doesn't rescue that: BN only takes bodies at a position the
        template already plays somewhere, not literally any NFL position.

        `plays_positions`, when set, answers this directly instead of deriving
        it — see that field for why a mid-draft config has to set it.
        """
        if self.plays_positions is not None:
            return [position for position in POSITIONS if position in self.plays_positions]

        positions = {position for position, count in self.starting_slots.items() if count > 0}
        for flex, count in self.flex_slots.items():
            if count > 0:
                positions.update(FLEX_ELIGIBILITY[flex])
        return [position for position in POSITIONS if position in positions]


LEAGUE_CONFIG = LeagueConfig(
    league_id="1372724723108036608",
    draft_id="1372724723120631808",
    season=2026,
    teams=12,
    budget=200,
    # Sleeper has no `min_bid` field in draft settings — $1 is the platform's
    # fixed auction floor, not a configurable league setting.
    min_bid=1,
    starting_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 0, "DEF": 1},
    flex_slots={"FLEX": 1, "REC_FLEX": 1, "SUPER_FLEX": 1},
    bench_slots=6,
)
