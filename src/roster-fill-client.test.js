import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

// roster-fill-client.cjs is real CommonJS (not affected by this package's
// "type": "module") so it can be inlined verbatim into a plain <script> tag
// in scripts/templates/board_slides.html with no import/export syntax that
// would break outside a module context.
const require = createRequire(import.meta.url);
const { fillSlots } = require("./roster-fill-client.cjs");

test("fillSlots seats the higher-points player when two compete for one slot", () => {
  const players = [
    { playerId: "lo", position: "RB", points: 10 },
    { playerId: "hi", position: "RB", points: 20 },
  ];
  const slots = [{ id: 1, eligiblePositions: ["RB"] }];
  const result = fillSlots(players, slots);
  assert.equal(result.get(1), "hi");
});

test("fillSlots reroutes an occupant via an augmenting path (flex contention)", () => {
  // Mirrors python/tests/test_replacement_level.py's flex-contention case:
  // a strong TE and a weaker RB both eligible for a shared FLEX slot, with
  // a dedicated TE slot behind the TE. The optimal fill seats both by
  // rerouting the TE out of FLEX into his own slot once the RB claims FLEX
  // -- not by leaving one of them out.
  const players = [
    { playerId: "te1", position: "TE", points: 100 },
    { playerId: "rb1", position: "RB", points: 90 },
  ];
  const slots = [
    { id: 1, eligiblePositions: ["TE"] },
    { id: 2, eligiblePositions: ["RB", "WR", "TE"] }, // FLEX
  ];
  const result = fillSlots(players, slots);
  assert.equal(result.size, 2);
  assert.deepEqual(new Set(result.values()), new Set(["te1", "rb1"]));
});

test("fillSlots is order-independent -- same players, different input order, same result", () => {
  const players = [
    { playerId: "a", position: "WR", points: 30 },
    { playerId: "b", position: "WR", points: 20 },
    { playerId: "c", position: "WR", points: 10 },
  ];
  const slots = [
    { id: 1, eligiblePositions: ["WR"] },
    { id: 2, eligiblePositions: ["WR"] },
  ];
  const forward = fillSlots(players, slots);
  const reversed = fillSlots([...players].reverse(), slots);
  assert.deepEqual([...forward.entries()].sort(), [...reversed.entries()].sort());
  // Only the top 2 by points make it -- "c" is left out either way.
  assert.deepEqual(new Set(forward.values()), new Set(["a", "b"]));
});

test("fillSlots leaves a player unassigned when no slot accepts his position", () => {
  const players = [{ playerId: "k1", position: "K", points: 50 }];
  const slots = [{ id: 1, eligiblePositions: ["RB"] }];
  const result = fillSlots(players, slots);
  assert.equal(result.size, 0);
});

test("fillSlots ties break on player_id ascending", () => {
  const players = [
    { playerId: "z", position: "RB", points: 10 },
    { playerId: "a", position: "RB", points: 10 },
  ];
  const slots = [{ id: 1, eligiblePositions: ["RB"] }];
  const result = fillSlots(players, slots);
  assert.equal(result.get(1), "a");
});
