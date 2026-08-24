import { test } from "node:test";
import assert from "node:assert/strict";
import { cacheBustedUrl, draftFingerprint, parseNomination, sleeperPlayerFullName, type Draft } from "./sleeper.ts";

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
