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
#: defense has a real starting slot and is fully draftable. K is the same
#: story in the snake league (SNAKE_CONFIG), which does play a kicker; the
#: auction league never drafts one at all, so listing it here is a no-op
#: there. Excluded from bench eligibility in last_rostered.py; still counted
#: normally everywhere else (its own concrete slot, replacement level).
STREAMING_POSITIONS = ("DEF", "K")

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


#: The snake keeper league — a different league from the auction one above,
#: sharing only the projections. Standard lineup with a single QB (no
#: superflex) and two RB/WR/TE flexes. `budget`/`min_bid` are unused here:
#: a snake draft has no money, and nothing in the points-based VORP/VOLR
#: math reads them. `draft_id` is left blank -- unlike the league id, Sleeper
#: mints a new draft id every season, so it has to be looked up fresh via
#: `GET /league/{league_id}/drafts` rather than hardcoded here.
SNAKE_CONFIG = LeagueConfig(
    league_id="1386051970791378944",
    draft_id="",
    season=2026,
    teams=10,
    budget=0,
    min_bid=0,
    starting_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1},
    flex_slots={"FLEX": 2},
    bench_slots=6,
)


# --------------------------------------------------------------------------
# Division/identity — board-labelling metadata, independent of the VORP math
# above. See docs/spec/board/02-seat-identity-and-divisions.md.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Division:
    name: str
    #: Sleeper usernames, case-sensitive as Sleeper reports them; matched
    #: case-insensitively by `division_index_for`.
    members: Tuple[str, ...]


#: The handle `resolve_my_seat` looks for, case-insensitively against a
#: seat's `username` or `display_name` (Sleeper often leaves one blank).
MY_USERNAME = "yidinghou"

#: Fixed seed for `random_fill`'s placeholder shuffle, so a mock draft's
#: seat assignment is identical every run — stable screenshots and tests.
MOCK_SEED = 20260827

#: Division membership by Sleeper username. **Placeholder members below**:
#: this league's real usernames aren't wired in yet. Bootstrap with
#: `python scripts/draft_board.py --draft-id <id> --print-seats` (prints
#: each seat's real `display_name`/`username`, read-only) and replace the
#: placeholders here — until every member is real, division grouping falls
#: back to an even auto-split by seat order, so the board still renders.
DIVISIONS: Tuple[Division, ...] = (
    Division(name="Division 1", members=("member1", "member2", "member3", "member4")),
    Division(name="Division 2", members=("member5", "member6", "member7", "member8")),
    Division(name="Division 3", members=("member9", "member10", "member11", MY_USERNAME)),
)


def all_members() -> List[str]:
    """Every Sleeper username across every division, flat — the pool
    `random_fill` shuffles from to seed placeholder managers."""
    return [member for division in DIVISIONS for member in division.members]


def division_index_for(username: Optional[str]) -> Optional[int]:
    """Which division a username belongs to, case-insensitive.

    None for a blank/absent username or one that matches no division member
    — the caller falls back to the auto-split-by-seat-order behavior.
    """
    if not username:
        return None
    needle = username.lower()
    for i, division in enumerate(DIVISIONS):
        if any(member.lower() == needle for member in division.members):
            return i
    return None
