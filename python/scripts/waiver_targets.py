#!/usr/bin/env python3
"""List Sleeper's trending-add players against a real league's free-agent
pool -- raw candidate discovery only, no scoring or verdicts. Use
python/data/notes/priors-*.md for the actual judgment call, and
waiver_claim.py to submit.

Usage:
    python scripts/waiver_targets.py --league-id 1386051970791378944
    python scripts/waiver_targets.py --league-id ... --lookback-hours 24 --limit 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from snake.queue_export import team_byes  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG, SNAKE_CONFIG, LeagueConfig  # noqa: E402
from vorp.sources.rotowire import fetch_headlines  # noqa: E402
from vorp.sources.sleeper import (  # noqa: E402
    fetch_league,
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
    parser.add_argument("--season", type=int, default=2026, help="for bye week lookup")
    args = parser.parse_args()

    trending = fetch_trending_adds(args.lookback_hours, args.limit)
    rosters = fetch_league_rosters(args.league_id)
    taken = rostered_player_ids(rosters)
    players = fetch_players_nfl()
    headlines = fetch_headlines()
    byes = team_byes(args.season)

    config = config_for_league_id(args.league_id)
    my_roster_size = None
    my_player_ids: list[str] = []
    faab_left = None
    if config is not None:
        my_roster_id = resolve_my_roster_id(args.league_id)
        my_roster = next((r for r in rosters if r.get("roster_id") == my_roster_id), None)
        my_player_ids = my_roster.get("players") or [] if my_roster else []
        my_starter_ids = set(my_roster.get("starters") or []) if my_roster else set()
        my_roster_size = len(my_player_ids)
        open_slot = my_roster_size is not None and my_roster_size < config.roster_size
        league = fetch_league(args.league_id)
        faab_total = (league.get("settings") or {}).get("waiver_budget")
        if faab_total is not None and my_roster is not None:
            used = (my_roster.get("settings") or {}).get("waiver_budget_used", 0) or 0
            faab_left = faab_total - used

    free_agents = [t for t in trending if t["player_id"] not in taken]

    print(f"Trending adds in the last {args.lookback_hours}h, filtered to free agents in this league:\n")
    print(f"  {'ADDS':>5}  {'POS':<4} {'TEAM':<5} {'BYE':<4} {'DEPTH':<6} {'NAME':<22} HEADLINE")
    for entry in free_agents:
        player = players.get(entry["player_id"], {})
        name = sleeper_player_full_name(player) or entry["player_id"]
        pos = player.get("position") or "?"
        team = player.get("team") or "FA"
        bye = byes.get(team, "-")
        depth = player.get("depth_chart_order")
        depth_str = str(depth) if depth is not None else "-"
        headline = headlines.get(name.lower(), "")
        print(f"  {entry['count']:>5}  {pos:<4} {team:<5} {bye:<4} {depth_str:<6} {name:<22} {headline}")

    if not free_agents:
        print("  (none of the trending adds are free agents here)")

    if my_roster_size is not None:
        print(f"\nYour roster: {my_roster_size}/{config.roster_size} spots filled.", end=" ")
        print("Open bench spot." if open_slot else "Full -- adding means dropping someone.")
        if faab_left is not None:
            print(f"FAAB left: ${faab_left}")

        print("\nYour bench (facts only, no ranking -- use your notes to decide):")
        for pid in my_player_ids:
            if pid in my_starter_ids:
                continue
            p = players.get(pid)
            if not p:
                continue
            name = sleeper_player_full_name(p) or pid
            team = p.get("team") or "FA"
            print(f"    {p.get('position', '?'):<4} {team:<5} bye {byes.get(team, '-'):<4} {name}")
    else:
        print("\n(--league-id doesn't match a known LeagueConfig, skipping roster-fit check)")


if __name__ == "__main__":
    main()
