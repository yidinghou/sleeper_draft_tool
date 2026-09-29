"""Local FAAB waiver-resolution simulator.

Models how a real Sleeper FAAB (auction-budget) waiver period resolves, so a
"waterfall" of fallback claims can be reasoned about before anything is
actually submitted (see scripts/waiver_sim.py). Pure -- no network, no I/O.

Rules modeled:
- Highest `faab_bid` on a given `add_player_id` wins it. Ties aren't modeled
  (they don't happen in practice with real FAAB budgets).
- A claim needs a `drop_player_id` unless the roster has an open slot.
- Waterfall double-drop: if two of one roster's claims name the same
  `drop_player_id`, the first to process (higher bid) wins and removes that
  player; the second then finds its drop target already gone and fails,
  even if its own bid would otherwise have won its own add target.

All claims across every roster are processed in one pass, sorted by
descending bid (`priority` only breaks ties within the same roster) --
this lets an already-won add or an already-consumed drop be visible to
every later claim for free, with no separate "already won" bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from vorp.league.config import LeagueConfig


@dataclass(frozen=True)
class RosterState:
    roster_id: int
    name: Optional[str]
    faab_budget_left: int
    player_ids: FrozenSet[str]
    open_slots: int


@dataclass(frozen=True)
class Claim:
    roster_id: int
    add_player_id: str
    drop_player_id: Optional[str]
    faab_bid: int
    priority: int = 0
    claim_id: Optional[str] = None


@dataclass(frozen=True)
class ClaimOutcome:
    claim: Claim
    won: bool
    reason: str


@dataclass(frozen=True)
class WaiverResult:
    outcomes: Tuple[ClaimOutcome, ...]
    rosters: Dict[int, RosterState]


def _sort_key(indexed_claim):
    index, claim = indexed_claim
    claim_id = claim.claim_id if claim.claim_id is not None else index
    return (-claim.faab_bid, claim.priority, claim.roster_id, claim_id)


def resolve_waivers(rosters: Dict[int, RosterState], claims: Sequence[Claim]) -> WaiverResult:
    working = dict(rosters)
    ordered = [claim for _, claim in sorted(enumerate(claims), key=_sort_key)]

    all_player_ids = set()
    for roster in working.values():
        all_player_ids.update(roster.player_ids)

    outcomes: List[ClaimOutcome] = []
    for claim in ordered:
        roster = working[claim.roster_id]

        if claim.add_player_id in all_player_ids:
            outcomes.append(ClaimOutcome(claim, False, "add_target_unavailable"))
            continue

        if claim.drop_player_id is not None:
            if claim.drop_player_id not in roster.player_ids:
                outcomes.append(ClaimOutcome(claim, False, "drop_target_not_rostered"))
                continue
        elif roster.open_slots <= 0:
            outcomes.append(ClaimOutcome(claim, False, "drop_required_no_open_slot"))
            continue

        if claim.faab_bid > roster.faab_budget_left:
            outcomes.append(ClaimOutcome(claim, False, "insufficient_budget"))
            continue

        new_player_ids = roster.player_ids
        if claim.drop_player_id is not None:
            new_player_ids = new_player_ids - {claim.drop_player_id}
            all_player_ids.discard(claim.drop_player_id)
        new_player_ids = new_player_ids | {claim.add_player_id}
        new_open_slots = roster.open_slots if claim.drop_player_id is not None else roster.open_slots - 1

        working[claim.roster_id] = replace(
            roster,
            player_ids=new_player_ids,
            open_slots=new_open_slots,
            faab_budget_left=roster.faab_budget_left - claim.faab_bid,
        )
        all_player_ids.add(claim.add_player_id)
        outcomes.append(ClaimOutcome(claim, True, "won"))

    return WaiverResult(outcomes=tuple(outcomes), rosters=working)


def roster_states_from_snapshot(
    rosters_raw: List[Dict],
    users_raw: List[Dict],
    config: LeagueConfig,
    faab_budget_total: int,
) -> Dict[int, RosterState]:
    names_by_user_id = {u["user_id"]: u.get("display_name") for u in users_raw}

    states = {}
    for roster in rosters_raw:
        roster_id = roster["roster_id"]
        player_ids = frozenset(roster.get("players") or [])
        used = (roster.get("settings") or {}).get("waiver_budget_used", 0) or 0
        states[roster_id] = RosterState(
            roster_id=roster_id,
            name=names_by_user_id.get(roster.get("owner_id")),
            faab_budget_left=faab_budget_total - used,
            player_ids=player_ids,
            open_slots=max(0, config.roster_size - len(player_ids)),
        )
    return states
