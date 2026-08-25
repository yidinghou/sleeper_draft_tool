#!/usr/bin/env python3
"""Blended-bar price export: one price per drafted player, at every floor
weight, plus how each one scores against the market.

The model (see vorp/models.py, `progressive_blend`, and docs/spec/vorp/04):

    w(p)   = w_floor + (1 - w_floor) * t,   t ramping 0 -> 1 in POINTS from
             the last-rostered level up to the full-weight point
    bar(p) = w(p) * replacement_level + (1 - w(p)) * last_rostered_level
    price  = apportion(teams * budget, max(0, points - bar(p)))

`w_floor` is the only dial, and a human sets it -- on the slider in the
exported page, or with --w-floor to choose where that slider starts.

The top `FULL_WEIGHT_SHARE` of starters sit above the ramp entirely, priced
against replacement level exactly as a starter should be. Below them the bar
slides toward the last-rostered level, so a marginal starter and a strong
bench pick land on one continuum instead of falling off a cliff between two
lenses. Because every player at a position is measured against a bar that
slides slower than his points do, price rises with points -- there is no
starter/bench seam to cross at any w_floor, which is what the retired
two-lens dial could never manage.

    w_floor = 1.0   pure VORP: bench picks fall below the bar and take the floor.
    w_floor = 0.0   the marginal band blends all the way to the last-rostered bar.

Writes data/blended-price-{season}.json plus a standalone .html and the
.artifact.html fragment to publish.

Usage: python scripts/blended_price.py [season] [--window=season|wk1_3]
                                       [--w-floor=0.5]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.bid_value import apportion_with_floor, floor_pressure  # noqa: E402
from vorp.csv_loader import load_players_from_csv, projections_csv_path, REPO_ROOT  # noqa: E402
from vorp.league_config import LEAGUE_CONFIG  # noqa: E402
from vorp.models import (  # noqa: E402
    FULL_WEIGHT_SHARE,
    DEFAULT_W_FLOOR,
    blend_weights,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bid_value import POINTS_COLUMNS, load_player_meta  # noqa: E402
from html_page import write_pair  # noqa: E402

HTML_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "blended_price.html"

#: Floor weights to solve for. 0.05 steps is finer than anyone can justify
#: from the data, but it makes the slider feel continuous.
WEIGHTS = [round(i * 0.05, 2) for i in range(21)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("season", type=int, nargs="?", default=LEAGUE_CONFIG.season)
    parser.add_argument("--window", choices=sorted(POINTS_COLUMNS), default="season")
    parser.add_argument(
        "--w-floor",
        type=float,
        default=DEFAULT_W_FLOOR,
        help="where the slider starts; the one dial (1.0 = pure VORP)",
    )
    args = parser.parse_args()

    config = LEAGUE_CONFIG
    season = args.season
    csv_path = projections_csv_path(season)
    players = load_players_from_csv(csv_path, points_column=POINTS_COLUMNS[args.window])
    meta = load_player_meta(csv_path)

    replacement, last_rostered, vorp_bar, volr_bar, ramps = blend_weights(players, config)
    by_id = {p.player_id: p for p in players}
    starters = set(replacement.selected_player_ids)
    drafted = set(last_rostered.selected_player_ids)

    positions = [pos for pos in ramps if pos in vorp_bar]
    ordered = sorted(
        (pid for pid in drafted if by_id[pid].position in positions),
        key=lambda pid: (-by_id[pid].points, pid),
    )

    total = config.teams * config.budget

    def ramp_weight(points: float, ramp: dict, w_floor: float) -> float:
        top, bottom = ramp["top"], ramp["bottom"]
        if points >= top or top <= bottom:
            t = 1.0
        elif points <= bottom:
            t = 0.0
        else:
            t = (points - bottom) / (top - bottom)
        return w_floor + (1 - w_floor) * t

    def solve(w_floor: float):
        bar = {}
        weights = {}
        for pid in ordered:
            player = by_id[pid]
            ramp = ramps[player.position]
            w = ramp_weight(player.points, ramp, w_floor)
            player_bar = w * ramp["replacement"] + (1 - w) * ramp["last_rostered"]
            bar[pid] = player_bar
            weights[pid] = max(0.0, player.points - player_bar)
        prices = apportion_with_floor(total, weights, config.min_bid)

        starter_spend = sum(prices[pid] for pid in ordered if pid in starters)
        bench_spend = sum(prices[pid] for pid in ordered if pid not in starters)
        priced_with_market = [
            (prices[pid], meta[pid]["sleeper_dollar"])
            for pid in ordered
            if meta.get(pid, {}).get("sleeper_dollar") is not None
        ]
        mae = sum(abs(a - b) for a, b in priced_with_market) / max(1, len(priced_with_market))

        # Monotonicity is guaranteed by the ramp-slope law; check it anyway,
        # because a guarantee nobody verifies is a comment.
        crossings = 0
        for pos in positions:
            ranked = [pid for pid in ordered if by_id[pid].position == pos]
            for better, worse in zip(ranked, ranked[1:]):
                if prices[worse] > prices[better]:
                    crossings += 1

        # The bar at the bottom and top of each position's ramp, for the
        # "where the bar sits" panel.
        bars = {
            pos: {
                "at_full_weight": round(
                    ramp_weight(ramps[pos]["top"], ramps[pos], w_floor)
                    * ramps[pos]["replacement"]
                    + (1 - ramp_weight(ramps[pos]["top"], ramps[pos], w_floor))
                    * ramps[pos]["last_rostered"],
                    1,
                ),
                "at_bottom": round(
                    w_floor * ramps[pos]["replacement"]
                    + (1 - w_floor) * ramps[pos]["last_rostered"],
                    1,
                ),
            }
            for pos in positions
        }

        return bar, prices, {
            "w_floor": w_floor,
            "starter_spend_per_team": round(starter_spend / config.teams, 1),
            "bench_spend_per_team": round(bench_spend / config.teams, 1),
            "market_mae": round(mae, 2),
            "top_price": max(prices.values()),
            "above_floor": sum(1 for v in prices.values() if v > config.min_bid),
            "floor_pressure": round(floor_pressure(total, len(prices), config.min_bid), 3),
            "crossings": crossings,
            "bars": bars,
        }

    solved = {w: solve(w) for w in WEIGHTS}
    default_w = min(WEIGHTS, key=lambda w: abs(w - args.w_floor))

    market_bench = (
        sum(
            meta.get(pid, {}).get("sleeper_dollar") or 0
            for pid in ordered
            if pid not in starters
        )
        / config.teams
    )
    market_starters = (
        sum(
            meta.get(pid, {}).get("sleeper_dollar") or 0
            for pid in ordered
            if pid in starters
        )
        / config.teams
    )

    # The two ends of the dial, as prices. Every blended price lies between
    # its player's own pair, so the pair is the range the slider moves him
    # through -- which end is the high one depends on the player: dropping
    # w_floor lifts the marginal band and, since the pool is fixed, takes it
    # from the top of the board.
    vorp_prices = solved[1.0][1]
    volr_prices = solved[0.0][1]

    rows = []
    for pid in ordered:
        p = by_id[pid]
        info = meta.get(pid, {})
        rows.append(
            {
                "player_id": pid,
                "name": info.get("name", pid),
                "team": info.get("team"),
                "position": p.position,
                "points": round(p.points, 1),
                "is_starter": pid in starters,
                "vorp": round(p.points - vorp_bar[p.position], 1),
                "volr": round(p.points - volr_bar[p.position], 1),
                "vorp_dollar": vorp_prices[pid],
                "volr_dollar": volr_prices[pid],
                "sleeper_dollar": info.get("sleeper_dollar"),
            }
        )

    payload = {
        "season": season,
        "window": args.window,
        "generated_from": str(csv_path.relative_to(REPO_ROOT)),
        "league": {
            "teams": config.teams,
            "budget": config.budget,
            "min_bid": config.min_bid,
            "bench_slots": config.bench_slots,
            "roster_size": config.roster_size,
        },
        "w_floor": default_w,
        "full_weight_share": FULL_WEIGHT_SHARE,
        "weights": WEIGHTS,
        "counts": {
            "starters": len(starters),
            "bench": len(ordered) - len(starters),
            "drafted": len(ordered),
        },
        "levels": {
            pos: {
                "replacement": round(ramps[pos]["replacement"], 1),
                "last_rostered": round(ramps[pos]["last_rostered"], 1),
                # Where the ramp starts: the top of the blended band.
                "full_weight": round(ramps[pos]["top"], 1),
            }
            for pos in positions
        },
        "market": {
            "starters_per_team": round(market_starters, 1),
            "bench_per_team": round(market_bench, 1),
            "top": max(
                (r["sleeper_dollar"] for r in rows if r["sleeper_dollar"] is not None),
                default=0,
            ),
        },
        "summary": [solved[w][2] for w in WEIGHTS],
        "players": rows,
        "prices": {
            f"{w:.2f}": [solved[w][1][pid] for pid in ordered] for w in WEIGHTS
        },
    }

    suffix = "" if args.window == "season" else f"-{args.window.replace('_', '-')}"
    stem = f"blended-price-{season}{suffix}"

    json_path = REPO_ROOT / "data" / f"{stem}.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {json_path.relative_to(REPO_ROOT)} ({len(rows)} drafted players)")

    template = HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    fragment = template.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    write_pair(fragment, REPO_ROOT / "data", stem)
    print(f"Wrote data/{stem}.artifact.html (publish) and data/{stem}.html (open)")

    s = solved[default_w][2]
    print(
        f"  w_floor={default_w}: starters ${s['starter_spend_per_team']}/team, "
        f"bench ${s['bench_spend_per_team']}/team "
        f"(market ${market_starters:.1f} / ${market_bench:.1f})"
    )
    print(f"  MAE ${s['market_mae']}, top ${s['top_price']}, crossings {s['crossings']}")


if __name__ == "__main__":
    main()
