import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from save_weekly_projections import out_path  # noqa: E402
from vorp.csv_loader import REPO_ROOT  # noqa: E402


def test_out_path_nests_by_season_and_week():
    assert out_path("2026", 2) == REPO_ROOT / "data" / "weekly-projections" / "2026" / "wk2.json"
