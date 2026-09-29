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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from snake.queue_export import team_byes  # noqa: E402
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


def classify_candidate(
    candidate: dict,
    my_players: list[dict],
    byes: dict[str, str],
    week: int | None,
) -> tuple[str, str]:
    """Tag a free agent as INSURANCE and/or STARTER, with a short reason.

    `candidate` and each entry in `my_players` are Sleeper player dicts (from
    fetch_players_nfl()), plus a "name" key for the reason text.
    """
    reasons = []
    tags = []

    team = candidate.get("team")
    position = candidate.get("position")
    depth_order = candidate.get("depth_chart_order")

    handcuff_target = next(
        (p for p in my_players if p.get("team") == team and p.get("position") == position),
        None,
    )
    if handcuff_target is not None:
        mate_order = handcuff_target.get("depth_chart_order")
        if depth_order is not None and mate_order is not None and depth_order > mate_order:
            tags.append("INSURANCE")
            reasons.append(f"backs up {handcuff_target['name']} (yours) at {position}-{team}")

    if week is not None:
        for mate in my_players:
            if mate.get("position") != position:
                continue
            mate_bye = byes.get(mate.get("team", ""))
            if mate_bye is not None and int(mate_bye) in (week, week + 1):
                tags.append("INSURANCE")
                reasons.append(f"{mate['team']} bye wk{mate_bye} -- you start a {position}")
                break

    if depth_order in (1, 2):
        tags.append("STARTER")
        reasons.append(f"{team} depth chart #{depth_order} at {position}")

    tag = "+".join(dict.fromkeys(tags)) if tags else ""
    return tag, "; ".join(reasons)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", required=True, help="see README.md's Leagues table")
    parser.add_argument("--lookback-hours", type=int, default=48)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--week", type=int, default=None, help="current NFL week, for bye-based insurance tags")
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
    my_players = []
    if config is not None:
        my_roster_id = resolve_my_roster_id(args.league_id)
        my_roster = next((r for r in rosters if r.get("roster_id") == my_roster_id), None)
        my_player_ids = my_roster.get("players") or [] if my_roster else []
        my_roster_size = len(my_player_ids)
        open_slot = my_roster_size is not None and my_roster_size < config.roster_size
        for pid in my_player_ids:
            p = players.get(pid)
            if p:
                my_players.append({**p, "name": sleeper_player_full_name(p) or pid})

    free_agents = [t for t in trending if t["player_id"] not in taken]

    print(f"Trending adds in the last {args.lookback_hours}h, filtered to free agents in this league:\n")
    print(f"  {'ADDS':>5}  {'POS':<4} {'TEAM':<5} {'NAME':<22} {'TAG':<18} WHY")
    for entry in free_agents:
        player = players.get(entry["player_id"], {})
        name = sleeper_player_full_name(player) or entry["player_id"]
        pos = player.get("position") or "?"
        team = player.get("team") or "FA"
        tag, reason = classify_candidate(player, my_players, byes, args.week)
        headline = headlines.get(name.lower(), "")
        why = "; ".join(w for w in (reason, headline) if w)
        print(f"  {entry['count']:>5}  {pos:<4} {team:<5} {name:<22} {tag:<18} {why}")

    if not free_agents:
        print("  (none of the trending adds are free agents here)")

    if my_roster_size is not None:
        print(f"\nYour roster: {my_roster_size}/{config.roster_size} spots filled.", end=" ")
        print("Open bench spot." if open_slot else "Full -- adding means dropping someone.")
    else:
        print("\n(--league-id doesn't match a known LeagueConfig, skipping roster-fit check)")


if __name__ == "__main__":
    main()
