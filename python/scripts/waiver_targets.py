#!/usr/bin/env python3
"""Rank Sleeper's trending-add players against a real league's free-agent
pool -- automates Step 1 of the sleeper-set-waivers skill instead of doing
it by hand.

Read-only: this only prints candidates. Use waiver_claim.py to actually
submit a claim.

Usage:
    python scripts/waiver_targets.py --league-id 1386051970791378944
    python scripts/waiver_targets.py --league-id ... --lookback-hours 24 --limit 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.league.config import LEAGUE_CONFIG, SNAKE_CONFIG, LeagueConfig  # noqa: E402
from vorp.sources.rotowire import fetch_headlines  # noqa: E402
from vorp.sources.sleeper import (  # noqa: E402
    fetch_league_rosters,
    fetch_players_nfl,
    fetch_trending_adds,
    sleeper_player_full_name,
)
from waiver_claim import resolve_my_roster_id  # noqa: E402

CONFIGS_BY_LEAGUE_ID = {c.league_id: c for c in (LEAGUE_CONFIG, SNAKE_CONFIG)}


def config_for_league_id(league_id: str) -> LeagueConfig:
    return CONFIGS_BY_LEAGUE_ID.get(league_id)


def rostered_player_ids(rosters: list) -> set:
    ids = set()
    for roster in rosters:
        ids.update(roster.get("players") or [])
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", required=True, help="see README.md's Leagues table")
    parser.add_argument("--lookback-hours", type=int, default=48)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    trending = fetch_trending_adds(args.lookback_hours, args.limit)
    rosters = fetch_league_rosters(args.league_id)
    taken = rostered_player_ids(rosters)
    players = fetch_players_nfl()
    headlines = fetch_headlines()

    config = config_for_league_id(args.league_id)
    my_roster_size = None
    if config is not None:
        my_roster_id = resolve_my_roster_id(args.league_id)
        my_roster = next((r for r in rosters if r.get("roster_id") == my_roster_id), None)
        my_roster_size = len(my_roster.get("players") or []) if my_roster else None
        open_slot = my_roster_size is not None and my_roster_size < config.roster_size

    free_agents = [t for t in trending if t["player_id"] not in taken]

    print(f"Trending adds in the last {args.lookback_hours}h, filtered to free agents in this league:\n")
    print(f"  {'ADDS':>5}  {'POS':<4} {'TEAM':<5} {'NAME':<22} WHY")
    for entry in free_agents:
        player = players.get(entry["player_id"], {})
        name = sleeper_player_full_name(player) or entry["player_id"]
        pos = player.get("position") or "?"
        team = player.get("team") or "FA"
        why = headlines.get(name.lower(), "")
        print(f"  {entry['count']:>5}  {pos:<4} {team:<5} {name:<22} {why}")

    if not free_agents:
        print("  (none of the trending adds are free agents here)")

    if my_roster_size is not None:
        print(f"\nYour roster: {my_roster_size}/{config.roster_size} spots filled.", end=" ")
        print("Open bench spot." if open_slot else "Full -- adding means dropping someone.")
    else:
        print("\n(--league-id doesn't match a known LeagueConfig, skipping roster-fit check)")


if __name__ == "__main__":
    main()
