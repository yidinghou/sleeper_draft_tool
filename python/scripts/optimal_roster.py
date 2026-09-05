#!/usr/bin/env python3
"""09 · The best affordable roster, printed -- see
docs/spec/vorp/09-optimal-roster.md.

Prices the board (opening, or residual against a --picks-file) and plans one
seat's best-affordable roster: the ordered buys, each with its price and the
marginal starting-lineup points it added, then (with --fill-all) the cheap
bodies that complete the rest of the roster.

Usage: python scripts/optimal_roster.py [season] --seat 3 [--picks-file <path>]
                                        [--w-floor 1.0] [--exclude K,DEF]
                                        [--fill-all]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.board import price_board  # noqa: E402
from vorp.csv_loader import load_players_from_csv, projections_csv_path  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG  # noqa: E402
from vorp.league.teams import LeagueState  # noqa: E402
from vorp.optimal_roster import plan_roster  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from draft_board import build_state  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("season", type=int, nargs="?", default=LEAGUE_CONFIG.season)
    parser.add_argument("--seat", type=int, required=True, help="1-indexed seat number")
    parser.add_argument("--picks-file", type=Path, default=None)
    parser.add_argument("--w-floor", type=float, default=1.0)
    parser.add_argument("--exclude", type=str, default="", help="comma-separated positions")
    parser.add_argument("--fill-all", action="store_true")
    args = parser.parse_args()

    config = LEAGUE_CONFIG
    players = load_players_from_csv(projections_csv_path(args.season))

    if args.picks_file:
        import json

        picks = json.loads(args.picks_file.read_text(encoding="utf-8")).get("picks", [])
        state = build_state(picks, config)
    else:
        state = LeagueState.opening(config)

    remaining = [p for p in players if p.player_id not in state.sold()]
    board = price_board(state, remaining, config, args.w_floor)
    prices = {pid: row["price"] for pid, row in board["rows"].items()}
    replacement = {pos: level["replacement"] for pos, level in board["levels"].items()}
    by_id = {p.player_id: p for p in remaining}
    meta_name: Dict[str, str] = {}  # no name source wired here -- print ids

    exclude = [p.strip().upper() for p in args.exclude.split(",") if p.strip()]
    seat_id = args.seat - 1
    plan = plan_roster(
        state,
        seat_id,
        remaining,
        prices,
        replacement,
        exclude_positions=exclude,
        fill_all=args.fill_all,
    )

    def label(pid: str) -> str:
        p = by_id.get(pid)
        return f"{pid} ({p.position})" if p else pid

    print(f"Seat {args.seat} -- best affordable roster (season {args.season})")
    print(f"  points before: {plan.points_before:.1f}  after: {plan.points_after:.1f}  gain: {plan.points_gain:.1f}")
    print(f"  spend: ${plan.spend}  reserve: ${plan.reserve}  budget left: ${plan.budget_left_after}")
    print(f"  open slots after: {plan.open_slots_after}")
    print("  targets:")
    for t in plan.targets:
        print(f"    {label(t.player_id):24s} ${t.price:<4d} +{t.points_gain:.1f} pts")
    if plan.fills:
        print("  fills:")
        for f in plan.fills:
            print(f"    {label(f.player_id):24s} ${f.price:<4d}")


if __name__ == "__main__":
    main()
