"""08 · What one seat should bid — see docs/spec/vorp/08-seat-value.md.

Everything in `models.py` prices the **board**: one number per player, the
same number for all twelve seats. That number answers "what is he worth in
this room", which is the right question right up until it's your turn to say
a number out loud, at which point two things about *your* seat matter and the
board price knows neither.

The first is your roster. A manager holding three running backs values a
fourth less than a manager holding none, and not as a matter of taste: the
fourth back reaches no slot that scores points, so he adds nothing. That is
`seat_vorp` below — the points a player adds to this seat's optimal starting
lineup, with every still-open slot imputed a freely-available body at its
position's replacement level.

The second is your budget, and it is the smaller correction: a board price can
simply exceed what a seat is allowed to bid. `seat_bid` clamps that. Clamping
is not a valuation — it never makes a player *worth* less, it only refuses to
advise an illegal bid.

The imputed body is the load-bearing choice. Measured against an *empty* slot
a player is worth his whole projection rather than his margin, which is the
one thing every model here refuses to do; the prototype that tried it valued
192 sold players at $13,472 against $2,400 of real money. Imputing a
replacement body is also what makes an empty seat agree with the board price
exactly, so this is a refinement of `04` rather than a rival to it.
"""

from __future__ import annotations

from math import floor
from typing import Dict, Iterable, List, Optional, Sequence

from .league.roster_fill import RosterFillPlayer, Slot, assign_to_slots
from .league.teams import UNKNOWN_SEAT, LeagueState, Seat


def seat_bid(price: int, state: LeagueState, seat_id: int) -> int:
    """The board price, clamped into what this seat can actually bid.

    Returns 0 when the seat cannot bid at all -- no such seat, no open roster
    spot, or not enough money left to cover the floor after reserving a dollar
    for each remaining spot. Zero is not a price here; it means "this seat is
    out", which is a different claim from `min_bid` ("it can have him for a
    dollar") and callers rely on being able to tell them apart.
    """
    cap = state.max_bid(seat_id)
    if cap is None or cap < state.config.min_bid:
        return 0
    return max(state.config.min_bid, min(price, cap))


def free_agents(
    slots: Sequence[Slot], replacement: Dict[str, float]
) -> List[RosterFillPlayer]:
    """The freely-available bodies, as players in the pool.

    A manager who leaves a slot open still starts *somebody* there -- the body
    a dollar buys, projected at his position's replacement level. Making those
    bodies explicit rather than scoring empty slots after the fact is what
    keeps the fill correct, and the reason is subtle enough to be worth
    stating.

    `assign_to_slots` maximizes the *count* of players seated, not the points
    on the field. Those are the same objective only while every slot is worth
    the same when empty. They are not: a seat with nine players and ten slots
    has several maximum matchings, and leaving the SUPER_FLEX open (which a
    free quarterback fills, at 214.8) is worth far more than leaving the
    REC_FLEX open (a free receiver, at 139.6). Scoring empty slots afterwards
    takes whichever matching Kuhn's happened to return and can be 75 points
    light.

    With the free agents in the pool every slot is filled, so the objective
    collapses back to "total points of the seated set" -- which is exactly the
    transversal matroid that `01-calculating-replacement.md` proves greedy
    points-descending selection solves optimally. One pool per position is
    enough to fill every slot that accepts it.
    """
    positions = {pos for slot in slots for pos in slot.eligible_positions}
    return [
        RosterFillPlayer(
            player_id=f"__free__{pos}__{i}",
            position=pos,
            points=replacement[pos],
        )
        for pos in sorted(positions)
        if pos in replacement
        for i in range(len(slots))
    ]


def _lineup_points(
    roster: Sequence[RosterFillPlayer],
    slots: Sequence[Slot],
    replacement: Dict[str, float],
) -> float:
    """Points of the best starting lineup this roster can field, counting a
    freely-available body in every slot nobody fills. See `free_agents`.
    """
    pool = list(roster) + free_agents(slots, replacement)
    by_id = {p.player_id: p for p in pool}
    seated = assign_to_slots(pool, list(slots))
    return sum(by_id[pid].points for pid in seated.values())


def _roster_of(
    seat: Seat, points_by_id: Dict[str, float]
) -> List[RosterFillPlayer]:
    """The seat's bought players as fill players.

    `Bought` carries no points -- it records a sale, not a projection -- so the
    caller supplies them. A player the projections no longer list (bought, then
    dropped from the source CSV) scores 0 rather than vanishing: he still
    occupies the slot, which is the part the lineup solve cares about.
    """
    return [
        RosterFillPlayer(
            player_id=b.player_id,
            position=b.position,
            points=points_by_id.get(b.player_id, 0.0),
        )
        for b in seat.bought
    ]


def seat_vorp(
    state: LeagueState,
    seat_id: int,
    candidate: RosterFillPlayer,
    replacement: Dict[str, float],
    points_by_id: Dict[str, float],
    baseline: Optional[float] = None,
) -> float:
    """Points `candidate` adds to this seat's optimal starting lineup.

    Zero when he reaches no startable slot and out-scores no current starter --
    the fourth running back on a roster whose RB-, flex- and superflex-eligible
    slots are all spoken for. That case is not special-cased anywhere; it is
    what the matching returns when no augmenting path exists.

    `baseline` is `_lineup_points` of the seat as it stands. It does not depend
    on the candidate, so `seat_values` solves it once per seat and passes it in;
    left None it is solved here.
    """
    seat = next((s for s in state.seats if s.seat_id == seat_id), None)
    if seat is None or seat.seat_id == UNKNOWN_SEAT:
        # The synthetic seat owns no roster template (docs/spec/league/03), so
        # there is no lineup to add to and no value to compute.
        return 0.0
    if any(b.player_id == candidate.player_id for b in seat.bought):
        raise ValueError(
            f"seat {seat_id} already owns {candidate.player_id}; the marginal "
            "value of a player you already have is not a meaningful number"
        )

    roster = _roster_of(seat, points_by_id)
    slots = state.seat_slots(seat, bench=False)
    if baseline is None:
        baseline = _lineup_points(roster, slots, replacement)
    with_him = _lineup_points(roster + [candidate], slots, replacement)
    return max(0.0, with_him - baseline)


def seat_values(
    state: LeagueState,
    seat_id: int,
    candidates: Iterable[RosterFillPlayer],
    replacement: Dict[str, float],
    points_by_id: Dict[str, float],
) -> Dict[str, float]:
    """`seat_vorp` for many candidates, solving the baseline once.

    The baseline is a fact about the seat, not about the man being valued, so
    hoisting it halves the lineup solves -- the difference between one solve
    per candidate and two.
    """
    seat = next((s for s in state.seats if s.seat_id == seat_id), None)
    if seat is None or seat.seat_id == UNKNOWN_SEAT:
        return {}

    roster = _roster_of(seat, points_by_id)
    slots = state.seat_slots(seat, bench=False)
    baseline = _lineup_points(roster, slots, replacement)
    owned = {b.player_id for b in seat.bought}

    return {
        c.player_id: seat_vorp(
            state, seat_id, c, replacement, points_by_id, baseline=baseline
        )
        for c in candidates
        if c.player_id not in owned
    }


def price_from_value(value: float, rate: float, state: LeagueState, seat_id: int) -> int:
    """A seat value in points, as whole dollars this seat may actually bid.

    `rate` is the league-wide exchange rate the board price runs on -- dollars
    per margin point -- so a seat bid and a board price are the same unit and
    can be shown side by side.

    Floored, not rounded: rounding up would advise a bid the model has just
    called too dear.
    """
    return seat_bid(state.config.min_bid + floor(rate * max(0.0, value)), state, seat_id)


def vorp_rate(pool: int, weights: Dict[str, float], min_bid: int) -> float:
    """Dollars per margin point, after every priced player is guaranteed the
    floor. The same rate `scripts/draft_demo.py` reports as `$/VORP pt`.
    """
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    return (pool - len(weights) * min_bid) / total
