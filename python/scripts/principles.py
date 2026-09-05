#!/usr/bin/env python3
"""Run every principle against every registered model and print the matrix.

The laws are pass/fail and a model that breaks one is broken, whatever its
numbers look like. The calibrations are graded and shown as measurements --
disagreeing with the market is allowed, and often the point.

Usage: python scripts/principles.py [season] [--window=season|wk1_3]
                                    [--model=NAME] [-v]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.csv_loader import load_players_from_csv, projections_csv_path  # noqa: E402
from vorp.league_config import LEAGUE_CONFIG  # noqa: E402
from vorp.models import REGISTRY  # noqa: E402
from vorp.principles import CALIBRATION, LAW, PRINCIPLES, Context, run  # noqa: E402

POINTS_COLUMNS = {"season": "season_pts_half_ppr", "wk1_3": "wk1_3_pts_half_ppr"}

TICK, CROSS = "PASS", "FAIL"


def load_market(csv_path: Path):
    market = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value = row.get("sleeper_proj_dollar") or None
            if value:
                market[row["player_id"]] = int(float(value))
    return market


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("season", type=int, nargs="?", default=LEAGUE_CONFIG.season)
    parser.add_argument("--window", choices=sorted(POINTS_COLUMNS), default="season")
    parser.add_argument("--model", action="append", help="run only these models")
    parser.add_argument("-v", "--verbose", action="store_true", help="show every detail line")
    args = parser.parse_args()

    csv_path = projections_csv_path(args.season)
    ctx = Context(
        players=load_players_from_csv(csv_path, points_column=POINTS_COLUMNS[args.window]),
        config=LEAGUE_CONFIG,
        market=load_market(csv_path),
    )

    names = args.model or list(REGISTRY)
    reports = {name: run(REGISTRY[name], ctx) for name in names}

    laws = [p for p in PRINCIPLES if p.kind == LAW]
    calibrations = [p for p in PRINCIPLES if p.kind == CALIBRATION]

    width = max(len(n) for n in names) + 2
    print(f"\nLAWS  ({len(laws)}) -- must hold, or the output isn't a price list\n")
    header = "".rjust(width) + "".join(p.id[:13].rjust(15) for p in laws) + "     score"
    print(header)
    print("-" * len(header))
    for name in names:
        report = reports[name]
        cells = "".join(
            (TICK if report.findings[p.id].passed else CROSS).rjust(15) for p in laws
        )
        score = f"{report.laws_passed()}/{report.laws_total()}"
        print(name.ljust(width) + cells + score.rjust(10))

    print(f"\nCALIBRATIONS  ({len(calibrations)}) -- graded, not pass/fail\n")
    header = "".rjust(width) + "".join(p.id[:13].rjust(16) for p in calibrations)
    print(header)
    print("-" * len(header))
    for name in names:
        report = reports[name]
        cells = ""
        for p in calibrations:
            f = report.findings[p.id]
            cells += (f"{f.measure}" if f.measure is not None else "--").rjust(16)
        print(name.ljust(width) + cells)

    print("\nWhat each principle says:\n")
    for p in PRINCIPLES:
        print(f"  [{p.kind:11}] {p.id:22} {p.statement}")

    failures = [
        (name, p, reports[name].findings[p.id])
        for name in names
        for p in laws
        if not reports[name].findings[p.id].passed
    ]
    if failures or args.verbose:
        print("\nDetail:\n")
        rows = (
            [(n, p, f) for n, p, f in failures]
            if not args.verbose
            else [(n, p, reports[n].findings[p.id]) for n in names for p in PRINCIPLES]
        )
        for name, principle, finding in rows:
            mark = TICK if finding.passed else CROSS
            print(f"  {mark}  {name:14} {principle.id:22} {finding.detail}")
    print()


if __name__ == "__main__":
    main()
