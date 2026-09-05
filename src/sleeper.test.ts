import { test } from "node:test";
import assert from "node:assert/strict";
import { cacheBustedUrl, draftFingerprint, parseNomination, scoreProjection, sleeperPlayerFullName, type Draft } from "./sleeper.ts";

test("cacheBustedUrl appends a timestamp query param to defeat CDN caching", () => {
  const url = cacheBustedUrl("/draft/123", () => 1724454000123);
  assert.equal(url, "https://api.sleeper.app/v1/draft/123?_cb=1724454000123");
});

test("cacheBustedUrl appends with & when the path already has a query string", () => {
  const url = cacheBustedUrl("/league/1/users?foo=bar", () => 42);
  assert.equal(url, "https://api.sleeper.app/v1/league/1/users?foo=bar&_cb=42");
});

test("draftFingerprint changes when the nominated player changes", () => {
  const base: Draft = {
    draft_id: "d1",
    league_id: "l1",
    season: "2026",
    type: "auction",
    status: "in_progress",
    settings: {},
    draft_order: null,
    metadata: { nominated_player_id: "100", highest_offer: "10", offering_slot: "2" },
  };
  const changed: Draft = {
    ...base,
    metadata: { ...base.metadata, nominated_player_id: "200" },
  };
  assert.notEqual(draftFingerprint(base), draftFingerprint(changed));
});

test("draftFingerprint is stable when nothing relevant changes", () => {
  const draft: Draft = {
    draft_id: "d1",
    league_id: "l1",
    season: "2026",
    type: "auction",
    status: "in_progress",
    settings: {},
    draft_order: null,
    metadata: { nominated_player_id: "100", highest_offer: "10", offering_slot: "2" },
  };
  assert.equal(draftFingerprint(draft), draftFingerprint({ ...draft }));
});

test("parseNomination reports no live nomination when the draft board is empty", () => {
  const draft: Draft = {
    draft_id: "d1",
    league_id: "l1",
    season: "2026",
    type: "auction",
    status: "not_started",
    settings: {},
    draft_order: null,
    metadata: {},
  };
  const nomination = parseNomination(draft);
  assert.equal(nomination.playerId, null);
  assert.equal(nomination.highestOffer, null);
});

test("parseNomination extracts the current high bid and offering seat", () => {
  const draft: Draft = {
    draft_id: "d1",
    league_id: "l1",
    season: "2026",
    type: "auction",
    status: "in_progress",
    settings: {},
    draft_order: null,
    metadata: {
      nominated_player_id: "4623",
      nominating_slot: "1",
      highest_offer: "42",
      offering_slot: "5",
    },
  };
  const nomination = parseNomination(draft);
  assert.deepEqual(nomination, {
    playerId: "4623",
    nominatingSlot: 1,
    highestOffer: 42,
    offeringSlot: 5,
  });
});

test("sleeperPlayerFullName prefers full_name when present", () => {
  const name = sleeperPlayerFullName({
    player_id: "1",
    first_name: "Patrick",
    last_name: "Mahomes",
    full_name: "Patrick Mahomes",
    position: "QB",
    team: "KC",
    status: "Active",
  });
  assert.equal(name, "Patrick Mahomes");
});

test("sleeperPlayerFullName falls back to first + last name", () => {
  const name = sleeperPlayerFullName({
    player_id: "1",
    first_name: "Patrick",
    last_name: "Mahomes",
    position: "QB",
    team: "KC",
    status: "Active",
  });
  assert.equal(name, "Patrick Mahomes");
});

// Jared Goff's real week-1 2026 projection, and the reason scoreProjection
// exists: Sleeper's own pts_half_ppr on this line is 20.34, because it pays 6
// for a passing TD. Both leagues here pay 4, and the app shows ~17.
const goffWeek1 = {
  player_id: "3163",
  pass_yd: 267.73,
  pass_td: 1.93,
  pass_int: 0.71,
  pass_2pt: 0.13,
  rush_yd: 3.14,
  rush_td: 0.06,
  fum: 0.5,
  fum_lost: 0.22,
  pts_half_ppr: 20.34,
};

test("scoreProjection uses the league's scoring, not Sleeper's half-PPR field", () => {
  const league = { pass_yd: 0.04, pass_td: 4, pass_int: -2, pass_2pt: 2,
                   rush_yd: 0.1, rush_td: 6, fum: -1, fum_lost: -2, rec: 0.5 };
  const points = scoreProjection(goffWeek1, league);
  assert.ok(Math.abs(points - 17.0) < 0.5, `expected ~17 under 4pt pass TDs, got ${points}`);

  // The same line at 6 points a passing TD is the number we were showing, and
  // is nearly four points richer -- the whole bug, in one assertion.
  const generic = scoreProjection(goffWeek1, { ...league, pass_td: 6 });
  assert.ok(generic - points > 3.5, `4pt vs 6pt TDs should differ by ~3.9, got ${generic - points}`);
});

test("scoreProjection ignores stats the league does not score and non-numeric fields", () => {
  const scored = scoreProjection({ player_id: "1", rec: 5, rec_yd: 60, gp: 1 },
                                 { rec: 0.5, rec_yd: 0.1, def_td: 6 });
  assert.equal(scored, 8.5);
  assert.equal(scoreProjection({ player_id: "1" }, { rec: 0.5 }), 0);
});
