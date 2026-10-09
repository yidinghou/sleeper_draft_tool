#!/usr/bin/env python3
"""Simulate FAAB waiver resolution locally -- who wins what, and why a
waterfall fallback claim fails -- without submitting anything real.

Usage:
    python scripts/waiver_sim.py claims.json
    python scripts/waiver_sim.py claims.json --league-id ... --faab-budget 100

Claims JSON:
    {
      "league_id": "...",
      "claims": [
        {"roster_id": 3, "add_player_id": "1234", "drop_player_id": "5678", "faab_bid": 15, "priority": 1},
        {"roster_id": 3, "add_player_id": "9999", "drop_player_id": "5678", "faab_bid": 8,  "priority": 2}
      ]
    }

See vorp/league/waivers.py for the resolution rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.league.waivers import Claim, resolve_waivers, roster_states_from_snapshot  # noqa: E402
from vorp.sources.sleeper import (  # noqa: E402
    fetch_league,
    fetch_league_rosters,
    fetch_league_users,
    fetch_players_nfl,
    sleeper_player_full_name,
)
from waiver_targets import config_for_league_id  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"


def load_claims(path: Path) -> Dict:
    raw = json.loads(path.read_text())
    claims = [
        Claim(
            roster_id=c["roster_id"],
            add_player_id=c["add_player_id"],
            drop_player_id=c.get("drop_player_id"),
            faab_bid=c["faab_bid"],
            priority=c.get("priority", 0),
            claim_id=c.get("claim_id"),
        )
        for c in raw["claims"]
    ]
    for c in claims:
        if c.faab_bid < 0:
            raise ValueError(f"negative faab_bid in claim: {c}")
    return {"league_id": raw.get("league_id"), "claims": claims}


def player_name(players: Dict, player_id: str) -> str:
    return sleeper_player_full_name(players.get(player_id, {})) or player_id


def print_console(result, players, roster_names) -> None:
    by_roster: Dict[int, list] = {}
    for outcome in result.outcomes:
        by_roster.setdefault(outcome.claim.roster_id, []).append(outcome)

    for roster_id, outcomes in by_roster.items():
        print(f"\nRoster {roster_id} ({roster_names.get(roster_id, '?')}):")
        for o in outcomes:
            c = o.claim
            add_name = player_name(players, c.add_player_id)
            drop_name = player_name(players, c.drop_player_id) if c.drop_player_id else "-"
            status = "WON " if o.won else "LOST"
            print(f"  [{status}] bid ${c.faab_bid:<4} add {add_name:<22} drop {drop_name:<22} ({o.reason})")

    print("\nBudgets/roster after:")
    for roster_id, roster in result.rosters.items():
        print(f"  Roster {roster_id} ({roster_names.get(roster_id, '?')}): "
              f"${roster.faab_budget_left} left, {roster.open_slots} open slots")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("claims_file", type=Path)
    parser.add_argument("--league-id", help="defaults to the claims file's own league_id")
    parser.add_argument("--faab-budget", type=int, help="override total season FAAB budget")
    parser.add_argument("--out", type=Path, help="defaults to data/waiver-sim-<league_id>.json")
    args = parser.parse_args()

    loaded = load_claims(args.claims_file)
    league_id = args.league_id or loaded["league_id"]
    if not league_id:
        parser.error("--league-id required (or set league_id in the claims file)")

    config = config_for_league_id(league_id)
    if config is None:
        parser.error(f"--league-id {league_id} doesn't match a known LeagueConfig")

    league = fetch_league(league_id)
    # waiver_budget is the live FAAB pool from league settings -- distinct from
    # LeagueConfig.budget, which is this league's auction *draft* budget.
    faab_budget_total = args.faab_budget
    if faab_budget_total is None:
        faab_budget_total = (league.get("settings") or {}).get("waiver_budget", config.budget)

    rosters_raw = fetch_league_rosters(league_id)
    users_raw = fetch_league_users(league_id)
    players = fetch_players_nfl()

    rosters = roster_states_from_snapshot(rosters_raw, users_raw, config, faab_budget_total)
    result = resolve_waivers(rosters, loaded["claims"])

    roster_names = {rid: r.name or str(rid) for rid, r in rosters.items()}
    print_console(result, players, roster_names)

    report = {
        "league_id": league_id,
        "claims_processed": [
            {
                "roster_id": o.claim.roster_id,
                "roster_name": roster_names.get(o.claim.roster_id),
                "add_player_id": o.claim.add_player_id,
                "add_name": player_name(players, o.claim.add_player_id),
                "drop_player_id": o.claim.drop_player_id,
                "drop_name": player_name(players, o.claim.drop_player_id) if o.claim.drop_player_id else None,
                "faab_bid": o.claim.faab_bid,
                "priority": o.claim.priority,
                "won": o.won,
                "reason": o.reason,
            }
            for o in result.outcomes
        ],
        "rosters_after": [
            {
                "roster_id": r.roster_id,
                "name": r.name,
                "faab_budget_left": r.faab_budget_left,
                "open_slots": r.open_slots,
                "player_ids": sorted(r.player_ids),
            }
            for r in result.rosters.values()
        ],
    }

    out_path = args.out or DATA_DIR / f"waiver-sim-{league_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
