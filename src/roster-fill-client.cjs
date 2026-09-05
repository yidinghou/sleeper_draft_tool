// Kuhn's-algorithm bipartite matching, ported from
// python/vorp/league/roster_fill.py::assign_to_slots -- see
// docs/spec/league/02-slot-assignment.md and
// docs/spec/board/03-rendering-contract.md's `fillSlots`.
//
// Plain JS, no imports, so it can be inlined as-is into
// scripts/templates/board_slides.html's <script> tag. draft_board.py's
// template-write step reads this file's source directly and inlines it,
// so there is one tested source of truth instead of a hand-copied,
// driftable duplicate of the Python matching.

function tryAssign(player, slots, slotOccupant, visited) {
  for (const slot of slots) {
    if (!slot.eligiblePositions.includes(player.position)) continue;
    if (visited.has(slot.id)) continue;
    visited.add(slot.id);

    const occupant = slotOccupant.get(slot.id);
    if (occupant === undefined || tryAssign(occupant, slots, slotOccupant, visited)) {
      slotOccupant.set(slot.id, player);
      return true;
    }
  }
  return false;
}

/**
 * players: [{playerId, position, points}]
 * slots: [{id, eligiblePositions: string[]}]
 * Returns Map<slotId, playerId> -- slot id to the player seated there.
 * A player who reaches no eligible open slot is simply absent from the
 * result, same as the Python side.
 */
function fillSlots(players, slots) {
  const ordered = [...players].sort((a, b) => {
    if (b.points !== a.points) return b.points - a.points;
    return a.playerId < b.playerId ? -1 : a.playerId > b.playerId ? 1 : 0;
  });

  const slotOccupant = new Map();
  for (const player of ordered) {
    tryAssign(player, slots, slotOccupant, new Set());
  }

  const result = new Map();
  for (const [slotId, player] of slotOccupant) {
    result.set(slotId, player.playerId);
  }
  return result;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { fillSlots };
}
