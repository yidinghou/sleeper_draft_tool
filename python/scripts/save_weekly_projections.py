#!/usr/bin/env python3
"""Save one week's Sleeper projections locally so later weeks build a
history instead of only ever seeing the latest API snapshot.

Usage:
    python scripts/save_weekly_projections.py --season 2026 --week 2 --league-id 1372724723108036608
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.csv_loader import REPO_ROOT  # noqa: E402
from vorp.sources.sleeper import fetch_league, fetch_weekly_projections, score_projection  # noqa: E402


def out_path(season: str, week: int) -> Path:
    return REPO_ROOT / "data" / "weekly-projections" / season / f"wk{week}.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--league-id", required=True, help="scores each projection in this league's rules")
    args = parser.parse_args()

    scoring = fetch_league(args.league_id).get("scoring_settings") or {}
    projections = fetch_weekly_projections(args.season, args.week)
    for projection in projections.values():
        projection["pts_league"] = score_projection(projection, scoring)

    path = out_path(args.season, args.week)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(projections))
    print(f"Saved {len(projections)} player projections (scored for league {args.league_id}) to {path}")


if __name__ == "__main__":
    main()
