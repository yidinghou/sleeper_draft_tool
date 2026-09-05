"""Shared by the replacement_level and last_rostered scripts: load a
RosterFillPlayer list from the projections CSV that
scripts/export-projections.ts (TypeScript) produces.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from .league_config import POSITIONS
from .roster_fill import RosterFillPlayer

REPO_ROOT = Path(__file__).resolve().parents[2]


def projections_csv_path(season: int) -> Path:
    return REPO_ROOT / "data" / f"projections-{season}.csv"


def load_players_from_csv(
    csv_path: Path, points_column: str = "season_pts_half_ppr"
) -> List[RosterFillPlayer]:
    players: List[RosterFillPlayer] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            position = row["position"]
            points = row[points_column]
            if position not in POSITIONS or not points:
                continue
            players.append(
                RosterFillPlayer(player_id=row["player_id"], position=position, points=float(points))
            )
    return players
