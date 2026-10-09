"""Self-check for waiver_targets.py's free-agent filtering."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from waiver_targets import rostered_player_ids  # noqa: E402


def test_rostered_player_ids_unions_every_roster() -> None:
    rosters = [{"players": ["1", "2"]}, {"players": ["3"]}, {"players": None}]
    assert rostered_player_ids(rosters) == {"1", "2", "3"}


if __name__ == "__main__":
    test_rostered_player_ids_unions_every_roster()
    print("ok")
