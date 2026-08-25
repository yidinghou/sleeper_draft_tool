#!/usr/bin/env python3
"""02 · Value over last rostered.

Reads the real projections CSV, computes per-position value-over-last-
rostered (docs/spec/vorp/02-value-over-last-rostered.md), prints a table,
and writes the result to data/last-rostered-{season}.json so other code can
load it without recomputing.

Usage: python scripts/last_rostered.py [season]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.csv_loader import load_players_from_csv, projections_csv_path, REPO_ROOT  # noqa: E402
from vorp.last_rostered import calculate_last_rostered_levels  # noqa: E402
from vorp.league_config import LEAGUE_CONFIG, POSITIONS  # noqa: E402


def print_table(by_position: dict, player_count: int, season: int) -> None:
    print(f"Value over last rostered per position ({season}, {player_count} players with a projection):\n")
    print(f"  {'POS':<3} {'PTS':>8}  {'CLEARED':>7}  EDGE")
    for position in POSITIONS:
        summary = by_position[position]
        if not summary.reachable:
            print(f"  {position:<3} {'unreachable':>8}  {'-':>7}  (no slot ever takes one)")
            continue
        print(
            f"  {position:<3} {summary.last_rostered_level:>8.1f}  {summary.selected_count:>7}"
            f"  #{summary.selected_count + 1} at the position"
        )


def main() -> None:
    season = int(sys.argv[1]) if len(sys.argv) > 1 else LEAGUE_CONFIG.season
    csv_path = projections_csv_path(season)
    players = load_players_from_csv(csv_path)

    result = calculate_last_rostered_levels(players, LEAGUE_CONFIG)
    print_table(result.by_position, len(players), season)

    out_path = REPO_ROOT / "data" / f"last-rostered-{season}.json"
    out_path.write_text(
        json.dumps(
            {
                "season": season,
                "generated_from": str(csv_path.relative_to(REPO_ROOT)),
                "player_count": len(players),
                "by_position": {
                    position: {
                        "reachable": summary.reachable,
                        "last_rostered_level": summary.last_rostered_level,
                        "selected_count": summary.selected_count,
                    }
                    for position, summary in result.by_position.items()
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
