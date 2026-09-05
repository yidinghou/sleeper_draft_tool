import { test } from "node:test";
import assert from "node:assert/strict";
import { buildPlayerIndex, matchSleeperPlayer, normalizeName } from "./boberto.ts";
import type { SleeperPlayer } from "./sleeper.ts";

function player(p: Partial<SleeperPlayer> & { player_id: string }): SleeperPlayer {
  return {
    first_name: "",
    last_name: "",
    position: "WR",
    team: null,
    status: "Active",
    ...p,
  } as SleeperPlayer;
}

const players: Record<string, SleeperPlayer> = {
  "1": player({ player_id: "1", full_name: "Marvin Harrison Jr.", position: "WR", team: "ARI" }),
  "2": player({ player_id: "2", full_name: "Amon-Ra St. Brown", position: "WR", team: "DET" }),
  // Sleeper lists Juszczyk as FB; the feeds call him an RB.
  "3": player({ player_id: "3", full_name: "Kyle Juszczyk", position: "FB", team: "SF" }),
  NYJ: player({ player_id: "NYJ", first_name: "New York", last_name: "Jets", position: "DEF", team: "NYJ" }),
  JAX: player({ player_id: "JAX", first_name: "Jacksonville", last_name: "Jaguars", position: "DEF", team: "JAX" }),
  // Two Mike Williamses; only the team breaks the tie.
  "4": player({ player_id: "4", full_name: "Mike Williams", position: "WR", team: "LAC" }),
  "5": player({ player_id: "5", full_name: "Mike Williams", position: "WR", team: "NYJ" }),
  // The feeds call him "Hollywood Brown"; Sleeper carries the legal name.
  "6": player({ player_id: "6", full_name: "Marquise Brown", position: "WR", team: "PHI" }),
};

const index = buildPlayerIndex(players);

test("normalizeName strips suffixes, punctuation and hyphens", () => {
  assert.equal(normalizeName("Marvin Harrison Jr."), "marvin harrison");
  assert.equal(normalizeName("Ja'Marr Chase"), "jamarr chase");
  assert.equal(normalizeName("Amon-Ra St. Brown"), "amon ra st brown");
});

test("matchSleeperPlayer resolves a skill player by name and position", () => {
  const hit = matchSleeperPlayer(index, { name: "Marvin Harrison", position: "WR", team: "ARI" });
  assert.equal(hit?.player_id, "1");
});

test("matchSleeperPlayer resolves defenses by team, whatever the feed calls them", () => {
  for (const name of ["Jets D/ST", "Jets", "New York Jets"]) {
    const hit = matchSleeperPlayer(index, { name, position: "DEF", team: "NYJ" });
    assert.equal(hit?.player_id, "NYJ", name);
  }
});

test("matchSleeperPlayer translates feed team abbreviations to Sleeper's", () => {
  const hit = matchSleeperPlayer(index, { name: "Jaguars D/ST", position: "DEF", team: "JAC" });
  assert.equal(hit?.player_id, "JAX");
});

test("matchSleeperPlayer falls back to name alone when positions disagree", () => {
  const hit = matchSleeperPlayer(index, { name: "Kyle Juszczyk", position: "RB", team: "SF" });
  assert.equal(hit?.player_id, "3");
});

test("matchSleeperPlayer breaks a duplicate-name tie on team", () => {
  const hit = matchSleeperPlayer(index, { name: "Mike Williams", position: "WR", team: "NYJ" });
  assert.equal(hit?.player_id, "5");
});

test("matchSleeperPlayer resolves a feed nickname to Sleeper's legal name", () => {
  const hit = matchSleeperPlayer(index, { name: "Hollywood Brown", position: "WR", team: "PHI" });
  assert.equal(hit?.player_id, "6");
});

test("matchSleeperPlayer returns null for an unknown name", () => {
  assert.equal(matchSleeperPlayer(index, { name: "Nobody Here", position: "RB", team: "ARI" }), null);
});
