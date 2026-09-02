#!/usr/bin/env python3
"""Player pool export: what each player is worth under VORP thinking and
under VOLR thinking, side by side, plus Sleeper's own projection.

**This export deliberately does NOT produce a single bid.** Any one
number has to pick a baseline for you, and the two baselines disagree
most exactly where the decision is hardest -- at the starter/bench
boundary. Collapsing them silently made a worse player look more
expensive than a better one (a bench QB out-pricing the last starting
QB, because one was measured against replacement level and the other
against the last-rostered bar). Two honest numbers and a human beat one
number with a hidden judgement baked in. See 03.

For every player at a position this league's roster template can ever
draft:

  - vorp_dollar: what he's worth if the WHOLE budget were apportioned by
    VORP (points - replacement_level, from 01) among everyone who clears
    replacement level -- i.e. every starter. Null for anyone who doesn't
    clear it.
  - volr_dollar: what he's worth if the WHOLE budget were apportioned by
    VOLR (points - last_rostered_level, from 02) among everyone who
    clears the last-rostered bar -- every starter AND every bench-only
    pick, since last-rostered's selected set is a superset of the
    starters'. Null only for someone who clears neither bar.
  - sleeper_dollar: Sleeper's own `sleeper_proj_dollar` projection from the
    source CSV, where available, as an outside reference point.

Both lenses spend the same whole budget, so the two columns are on the
same scale and each independently sums to teams * budget. Read the gap
between them, not either alone: a big VORP $ with a small VOLR $ means a
player whose value is concentrated in being startable; the reverse means
depth that holds up against the waiver wire.

Writes data/bid-value-{season}.json, or data/bid-value-{season}-wk1-3.json
when --window=wk1_3 is passed (points priced off projected weeks 1-3 only,
instead of the full season -- same VORP/VOLR/bid math, just over a
different points column from the same CSV).

Usage: python scripts/bid_value.py [season] [--window=season|wk1_3]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.bid_value import (  # noqa: E402
    _effective_bar,
    apportion_with_floor,
    floor_pressure,
)
from vorp.csv_loader import load_players_from_csv, projections_csv_path, REPO_ROOT  # noqa: E402
from vorp.last_rostered import calculate_last_rostered_levels  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG  # noqa: E402
from vorp.replacement_level import calculate_replacement_levels  # noqa: E402


def load_player_meta(csv_path: Path) -> Dict[str, dict]:
    """csv_loader strips names/teams/Sleeper's own $ projection down to what
    the solver needs; pull them back in separately for display.
    """
    meta: Dict[str, dict] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sleeper_dollar = row.get("sleeper_proj_dollar") or None
            meta[row["player_id"]] = {
                "name": row["player"],
                "team": row["team"] or None,
                "sleeper_dollar": int(float(sleeper_dollar)) if sleeper_dollar else None,
            }
    return meta


POINTS_COLUMNS = {"season": "season_pts_half_ppr", "wk1_3": "wk1_3_pts_league"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("season", type=int, nargs="?", default=LEAGUE_CONFIG.season)
    parser.add_argument("--window", choices=sorted(POINTS_COLUMNS), default="season")
    args = parser.parse_args()

    season = args.season
    points_column = POINTS_COLUMNS[args.window]
    csv_path = projections_csv_path(season)
    players = load_players_from_csv(csv_path, points_column=points_column)
    meta = load_player_meta(csv_path)

    replacement = calculate_replacement_levels(players, LEAGUE_CONFIG)
    last_rostered = calculate_last_rostered_levels(players, LEAGUE_CONFIG)

    starters = replacement.selected_player_ids
    drafted = last_rostered.selected_player_ids  # superset of starters

    total = LEAGUE_CONFIG.teams * LEAGUE_CONFIG.budget

    vorp_bar = {
        pos: _effective_bar(s.replacement_level, pos, players)
        for pos, s in replacement.by_position.items()
        if s.reachable
    }
    volr_bar = {
        pos: _effective_bar(s.last_rostered_level, pos, players)
        for pos, s in last_rostered.by_position.items()
        if s.reachable
    }

    vorp_weights = {
        p.player_id: p.points - vorp_bar[p.position]
        for p in players
        if p.player_id in starters
    }
    volr_weights = {
        p.player_id: p.points - volr_bar[p.position]
        for p in players
        if p.player_id in drafted
    }

    # Each lens spends the WHOLE budget on its own thinking, so the two
    # dollar figures land on the same scale and can be read against each
    # other. Sizing them 90/10 instead would put VORP $ around $18 and
    # VOLR $ around $3 for the same player -- different scales, nothing a
    # human could weigh. The 90/10 split only ever existed to size the two
    # halves of a single blended bid; nothing produces one any more, so the
    # split is gone rather than kept around unused. See 03, and 04 for the
    # blend that replaced it.
    vorp_shares = apportion_with_floor(total, vorp_weights, LEAGUE_CONFIG.min_bid)
    volr_shares = apportion_with_floor(total, volr_weights, LEAGUE_CONFIG.min_bid)

    lens_floor_pressure = {
        "vorp": round(floor_pressure(total, len(vorp_weights), LEAGUE_CONFIG.min_bid), 3),
        "volr": round(floor_pressure(total, len(volr_weights), LEAGUE_CONFIG.min_bid), 3),
    }

    rows = []
    for p in players:
        pos_last_rostered = last_rostered.by_position[p.position]
        if not pos_last_rostered.reachable:
            continue  # e.g. K in this league -- never draftable, skip entirely
        pos_replacement = replacement.by_position[p.position]

        has_vorp = p.player_id in vorp_weights
        has_volr = p.player_id in volr_weights
        info = meta.get(p.player_id, {})

        rows.append(
            {
                "player_id": p.player_id,
                "name": info.get("name", p.player_id),
                "team": info.get("team"),
                "position": p.position,
                "points": round(p.points, 1),
                "is_starter": p.player_id in starters,
                "drafted": p.player_id in drafted,
                "vorp": round(p.points - vorp_bar[p.position], 1),
                # apportion_with_floor already includes the min_bid floor.
                "vorp_dollar": vorp_shares[p.player_id] if has_vorp else None,
                "volr": round(p.points - volr_bar[p.position], 1),
                "volr_dollar": volr_shares[p.player_id] if has_volr else None,
                "sleeper_dollar": info.get("sleeper_dollar"),
            }
        )

    rows.sort(key=lambda r: r["points"], reverse=True)

    suffix = "" if args.window == "season" else f"-{args.window.replace('_', '-')}"
    out_path = REPO_ROOT / "data" / f"bid-value-{season}{suffix}.json"
    out_path.write_text(
        json.dumps(
            {
                "season": season,
                "window": args.window,
                "generated_from": str(csv_path.relative_to(REPO_ROOT)),
                "league": {
                    "teams": LEAGUE_CONFIG.teams,
                    "budget": LEAGUE_CONFIG.budget,
                    "min_bid": LEAGUE_CONFIG.min_bid,
                },
                # Two independent whole-budget lenses. Deliberately no single
                # "bid" -- see 03. Each spends `total` on its own thinking,
                # so both columns sit on the same scale and can be weighed
                # against each other by eye.
                "lens": {
                    "vorp": {
                        "pool": total,
                        "members": len(vorp_weights),
                        "floor_pressure": lens_floor_pressure["vorp"],
                        "population": "clears replacement level (starters)",
                    },
                    "volr": {
                        "pool": total,
                        "members": len(volr_weights),
                        "floor_pressure": lens_floor_pressure["volr"],
                        "population": "clears the last-rostered bar (everyone drafted)",
                    },
                },
                "positions": {
                    pos: {
                        "pool": sum(1 for p in players if p.position == pos),
                        "starters": replacement.by_position[pos].selected_count,
                        "drafted": last_rostered.by_position[pos].selected_count,
                        "replacement_level": round(vorp_bar[pos], 2),
                        "last_rostered_level": round(volr_bar[pos], 2),
                        # True = the projections ran out before the league's
                        # slots did, so the bar is a floor-bound stand-in
                        # rather than a real next-best player.
                        "replacement_pool_exhausted": replacement.by_position[pos].pool_exhausted,
                        "last_rostered_pool_exhausted": last_rostered.by_position[pos].pool_exhausted,
                    }
                    for pos in vorp_bar
                },
                "player_count": len(rows),
                "players": rows,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {out_path.relative_to(REPO_ROOT)} ({len(rows)} players)")


if __name__ == "__main__":
    main()
