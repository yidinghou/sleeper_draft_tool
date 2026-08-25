"""The league as seats holding real slots — see docs/spec/vorp/06.

`LeagueConfig` is a *template*: one seat's worth of roster spots, per team. It
is the right shape for describing the rules and the wrong shape for describing
a draft in progress, because a per-team count cannot express a single sale.
This league wants 2 RB per team, so demand is 24 RB slots; 23 is not a number
the template can hold, and dividing back down gives `23 // 12 = 1` — one sale
read as all twelve seats filling a running back.

So demand lives here instead, as one `Slot` object per seat per roster spot.
The models are unchanged: they take a flat list of slots, and this module is
what builds it. Pre-draft the list is identical to the `count * teams`
expansion it replaces; each sale removes exactly one slot from it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

from .config import (
    FLEX_ELIGIBILITY,
    POSITIONS,
    STREAMING_POSITIONS,
    LeagueConfig,
)
from .roster_fill import RosterFillPlayer, Slot, assign_to_slots

#: Seat id given to a sale whose buyer we don't know — manual entry, where the
#: room says "Gibbs, $60" and nobody records who won him. The slot and the
#: money still leave the league, so every league-wide number stays exact; it is
#: only this seat's own budget and max bid that become fiction. See 06's catch.
UNKNOWN_SEAT = -1


@dataclass(frozen=True)
class Bought:
    """A player a seat owns, and what it paid."""

    player_id: str
    position: str
    amount: int


@dataclass(frozen=True)
class Seat:
    seat_id: int
    budget_left: int
    bought: Tuple[Bought, ...] = ()
    #: Sleeper's display name for the manager, when we have one.
    name: Optional[str] = None

    def spent(self) -> int:
        return sum(b.amount for b in self.bought)


@dataclass(frozen=True)
class LeagueState:
    """The seats, plus the template they were cut from."""

    config: LeagueConfig
    seats: Tuple[Seat, ...]

    # ---------------------------------------------------------------- build

    @classmethod
    def opening(cls, config: LeagueConfig) -> "LeagueState":
        """Every seat full of money and empty of players."""
        return cls(
            config=config,
            seats=tuple(
                Seat(seat_id=i, budget_left=config.budget) for i in range(config.teams)
            ),
        )

    def sell(
        self,
        player_id: str,
        position: str,
        amount: int,
        seat_id: Optional[int] = None,
    ) -> "LeagueState":
        """Hand a player to a seat. Returns a new state; nothing mutates.

        `seat_id=None` means the buyer is unknown, which is what manual entry
        gives us — the sale lands on UNKNOWN_SEAT.
        """
        target = UNKNOWN_SEAT if seat_id is None else seat_id
        bought = Bought(player_id=player_id, position=position, amount=amount)

        seats = list(self.seats)
        for i, seat in enumerate(seats):
            if seat.seat_id == target:
                seats[i] = replace(
                    seat,
                    budget_left=seat.budget_left - amount,
                    bought=seat.bought + (bought,),
                )
                break
        else:
            # First unattributed sale: the synthetic seat starts with no money,
            # so its budget goes negative and the league pool still nets out to
            # exactly the money actually left in the room.
            seats.append(Seat(seat_id=target, budget_left=-amount, bought=(bought,)))

        return replace(self, seats=tuple(seats))

    # ---------------------------------------------------------------- slots

    def _seat_slots(self, seat: Seat, bench: bool, start_id: int) -> List[Slot]:
        """One seat's roster spots, as slot objects.

        `bench=False` gives the starting slots only (what 01 fills against);
        `bench=True` adds the bench (what 02 fills against). Bench slots take
        any position the template plays somewhere, minus the streamed ones —
        the rule that used to live in last_rostered.py.
        """
        slots: List[Slot] = []
        next_id = start_id

        for position in POSITIONS:
            for _ in range(self.config.starting_slots.get(position, 0)):
                slots.append(
                    Slot(
                        id=next_id,
                        eligible_positions=(position,),
                        seat_id=seat.seat_id,
                    )
                )
                next_id += 1

        for flex, count in self.config.flex_slots.items():
            for _ in range(count):
                slots.append(
                    Slot(
                        id=next_id,
                        eligible_positions=tuple(FLEX_ELIGIBILITY[flex]),
                        seat_id=seat.seat_id,
                    )
                )
                next_id += 1

        if bench:
            bench_eligible = tuple(
                p
                for p in self.config.draftable_positions()
                if p not in STREAMING_POSITIONS
            )
            for _ in range(self.config.bench_slots):
                slots.append(
                    Slot(
                        id=next_id,
                        eligible_positions=bench_eligible,
                        seat_id=seat.seat_id,
                    )
                )
                next_id += 1

        return slots

    def all_slots(self, bench: bool) -> List[Slot]:
        """Every seat's roster spots, filled or not, as one flat list.

        Pre-draft this *is* the league's demand, and it is identical to the
        `count * teams` expansion it replaces — same per-position capacity, in
        the same order.
        """
        slots: List[Slot] = []
        next_id = 0
        for seat in self.seats:
            if seat.seat_id == UNKNOWN_SEAT:
                # The synthetic seat is an accounting device, not a 13th team;
                # it owns no roster template and contributes no demand.
                continue
            seat_slots = self._seat_slots(seat, bench=bench, start_id=next_id)
            next_id += len(seat_slots)
            slots.extend(seat_slots)
        return slots

    def _filled_slot_ids(self, seat: Seat, bench: bool, start_id: int) -> set:
        """Which of one seat's slots its players occupy.

        This is the same bipartite matching the league-wide fill uses, run over
        one seat. A greedy rule -- concrete slot, else flex, else bench --
        would depend on the order the seat happened to buy in; the matching
        does not.
        """
        slots = self._seat_slots(seat, bench=bench, start_id=start_id)
        players = [
            RosterFillPlayer(player_id=b.player_id, position=b.position, points=0.0)
            for b in seat.bought
        ]
        return set(assign_to_slots(players, slots).keys())

    def open_slots(self, bench: bool) -> List[Slot]:
        """The league's remaining demand: every slot no seat has filled yet."""
        slots: List[Slot] = []
        # Ids have to stay unique across seats -- the matching keys its
        # occupied/visited sets by slot id -- so the counter advances by every
        # slot generated, not just the ones that survive the filter.
        next_id = 0
        for seat in self.seats:
            if seat.seat_id == UNKNOWN_SEAT:
                continue
            seat_slots = self._seat_slots(seat, bench=bench, start_id=next_id)
            filled = self._filled_slot_ids(seat, bench=bench, start_id=next_id)
            next_id += len(seat_slots)
            slots.extend(s for s in seat_slots if s.id not in filled)
        return slots

    def starting_slots(self) -> List[Slot]:
        """Open starting slots (concrete + flex) — what 01 fills against."""
        return self.open_slots(bench=False)

    def full_roster_slots(self) -> List[Slot]:
        """Open roster slots including bench — what 02 fills against."""
        return self.open_slots(bench=True)

    # ------------------------------------------------------------- readouts

    def sold(self) -> Dict[str, int]:
        """Every player bought so far, and what he went for."""
        return {b.player_id: b.amount for seat in self.seats for b in seat.bought}

    def spent(self) -> int:
        return sum(seat.spent() for seat in self.seats)

    def pool(self) -> int:
        """The money still in the room. `teams * budget` pre-draft."""
        return self.config.teams * self.config.budget - self.spent()

    def spots_left(self) -> int:
        return len(self.full_roster_slots())

    def max_bid(self, seat_id: int) -> Optional[int]:
        """The most this seat can put on one player: its budget, less a dollar
        held back for every *other* spot it still has to fill.
        """
        seat = next((s for s in self.seats if s.seat_id == seat_id), None)
        if seat is None:
            return None
        open_count = sum(
            1 for s in self.full_roster_slots() if s.seat_id == seat_id
        )
        if open_count == 0:
            return 0
        return seat.budget_left - (open_count - 1) * self.config.min_bid
