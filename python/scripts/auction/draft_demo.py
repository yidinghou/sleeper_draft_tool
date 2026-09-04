#!/usr/bin/env python3
"""Scripted drafts, replayed against the live league state -- see
docs/spec/league/03-seats-and-sales.md.

The pre-draft price list can't show what the seat/slot model buys us, because
pre-draft the model is deliberately invisible: every slot is open and the
numbers are identical to the expansion it replaced. What it changes is what
happens *after* a sale, so this exports a timeline instead of a table -- one
per scripted scenario, plus a landing page that puts them side by side.

Each scenario runs the same market-order sale sequence through a different
mispricing rule, because that is when the model has something to say: money
leaving the room faster than value does makes everyone left cheaper, and the
reverse makes them dearer.

Writes, per scenario, data/draft-demo-{season}-{scenario}.json and the local
.html (open directly in a browser). Also writes the landing page,
data/draft-demo-{season}.html, linking to all of them.

Usage: python scripts/draft_demo.py [season] [--picks=60] [--w-floor=1.0]
                                    [--scenario=all|bargain-run|panic-run|
                                     position-runs|fair-market]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vorp.board import price_board  # noqa: E402
from vorp.csv_loader import load_players_from_csv, projections_csv_path, REPO_ROOT  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG  # noqa: E402
from vorp.league.teams import LeagueState  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bid_value import POINTS_COLUMNS, load_player_meta  # noqa: E402
from html_page import write_local  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent / "templates"
DEMO_TEMPLATE_PATH = TEMPLATES / "draft_demo.html"
INDEX_TEMPLATE_PATH = TEMPLATES / "draft_demo_index.html"

#: A scenario is a mispricing rule: (position, overall pick index, how many
#: of that position have sold so far) -> the multiplier applied to market
#: price. `order` below is fixed across scenarios (richest player first), so
#: "pick index" means the same player in every scenario -- what changes is
#: only what he sells for.
MultiplierFn = Callable[[str, int, Dict[str, int]], float]

SCENARIOS: Dict[str, Dict] = {
    "fair-market": {
        "title": "Fair market",
        "blurb": (
            "Every player sells at market, no mispricing at all. The "
            "control: price should barely move off its opening number, "
            "because nothing about the room's spending is out of the "
            "ordinary."
        ),
        "multiplier": lambda position, i, sold: 1.0,
    },
    "bargain-run": {
        "title": "Bargain run",
        "blurb": (
            "The first 15 picks -- the best players on the board -- go for "
            "45% off market. Money stays in the room faster than value "
            "leaves it, so every player still on the board gets more "
            "expensive, not cheaper."
        ),
        "multiplier": lambda position, i, sold: 0.55 if i < 15 else 1.0,
    },
    "panic-run": {
        "title": "Panic run",
        "blurb": (
            "The first 15 picks go for 40% over market. Money leaves the "
            "room faster than value does, so every player still on the "
            "board gets cheaper."
        ),
        "multiplier": lambda position, i, sold: 1.40 if i < 15 else 1.0,
    },
    "position-runs": {
        "title": "Position runs",
        "blurb": (
            "The room pays 35% over for the first 12 running backs, then "
            "goes 25% under for the first 14 receivers. Two positions move "
            "in opposite directions at once, and each position's own bar "
            "only starts to slide once it sells past its own concrete "
            "slots."
        ),
        "multiplier": lambda position, i, sold: (
            1.35
            if position == "RB" and sold.get("RB", 0) < 12
            else 0.75 if position == "WR" and sold.get("WR", 0) < 14 else 1.0
        ),
    },
}


def seat_rows(state: LeagueState) -> List[Dict]:
    """Per-seat readouts: what each manager has left to spend it on."""
    open_by_seat: Dict[int, int] = {}
    for slot in state.full_roster_slots():
        open_by_seat[slot.seat_id] = open_by_seat.get(slot.seat_id, 0) + 1
    return [
        {
            "seat": seat.seat_id,
            "budget": seat.budget_left,
            "spots": open_by_seat.get(seat.seat_id, 0),
            "max_bid": state.max_bid(seat.seat_id),
            "bought": [b.position for b in seat.bought],
        }
        for seat in state.seats
        if seat.seat_id >= 0
    ]


def run_scenario(
    key: str,
    multiplier: MultiplierFn,
    *,
    config,
    players: List,
    meta: Dict,
    by_id: Dict,
    order: List[str],
    opening_rows: Dict,
    picks: int,
    w_floor: float,
) -> Dict:
    """Replay one scenario's mispricing rule over the fixed sale order,
    starting fresh from the (shared, already-solved) opening board.
    """

    def name(pid: str) -> str:
        return meta.get(pid, {}).get("name", pid)

    state = LeagueState.opening(config)
    remaining = list(players)

    frames = [
        {
            "pick": 0,
            "sold": None,
            "pool": state.pool(),
            "spots_left": state.spots_left(),
            "vorp_rate": opening_rows["vorp_rate"],
            "levels": opening_rows["levels"],
            "rows": opening_rows["rows"],
            "seats": seat_rows(state),
        }
    ]

    sold_count: Dict[str, int] = {}
    ledger = []

    for i, pid in enumerate(order[:picks]):
        pick = i + 1
        position = by_id[pid].position
        factor = multiplier(position, i, sold_count)
        amount = max(config.min_bid, round(meta[pid]["sleeper_dollar"] * factor))
        sold_count[position] = sold_count.get(position, 0) + 1

        seat_id = i % config.teams
        our_price = frames[-1]["rows"].get(pid, {}).get("price")

        state = state.sell(pid, position, amount, seat_id=seat_id)
        remaining = [p for p in remaining if p.player_id != pid]
        shot = price_board(state, remaining, config, w_floor)

        ledger.append(
            {
                "pick": pick,
                "player_id": pid,
                "name": name(pid),
                "position": position,
                "team": meta.get(pid, {}).get("team"),
                "amount": amount,
                "our_price": our_price,
                "seat": seat_id,
            }
        )
        frames.append(
            {
                "pick": pick,
                "sold": ledger[-1],
                "pool": state.pool(),
                "spots_left": state.spots_left(),
                "vorp_rate": shot["vorp_rate"],
                "levels": shot["levels"],
                "rows": shot["rows"],
                "seats": seat_rows(state),
            }
        )

    scenario = SCENARIOS[key]
    return {
        "key": key,
        "title": scenario["title"],
        "blurb": scenario["blurb"],
        "frames": frames,
        "ledger": ledger,
    }


def write_scenario_page(payload: Dict, config, args, board: List[str], meta, by_id, name_fn) -> None:
    stem = f"draft-demo-{args.season}-{payload['key']}"
    full = dict(payload)
    full.update(
        {
            "season": args.season,
            "window": args.window,
            "w_floor": args.w_floor,
            "league": {
                "teams": config.teams,
                "budget": config.budget,
                "min_bid": config.min_bid,
                "bench_slots": config.bench_slots,
                "roster_size": config.roster_size,
            },
            "players": [
                {
                    "player_id": pid,
                    "name": name_fn(pid),
                    "team": meta.get(pid, {}).get("team"),
                    "position": by_id[pid].position,
                    "points": round(by_id[pid].points, 1),
                    "opening": payload["frames"][0]["rows"][pid]["price"],
                    "market": meta.get(pid, {}).get("sleeper_dollar"),
                }
                for pid in board
            ],
        }
    )

    json_path = REPO_ROOT / "data" / "auction" / f"{stem}.json"
    json_path.write_text(json.dumps(full, indent=2) + "\n")

    template = DEMO_TEMPLATE_PATH.read_text(encoding="utf-8")
    fragment = template.replace("__DATA__", json.dumps(full, separators=(",", ":")))
    write_local(fragment, REPO_ROOT / "data" / "auction", stem)

    last = full["frames"][-1]
    print(
        f"  [{payload['key']}] {len(full['frames'])} frames, {len(board)} players -- "
        f"pool ${last['pool']}, {last['spots_left']} spots left, "
        f"${last['vorp_rate']}/VORP pt (open ${full['frames'][0]['vorp_rate']})"
    )


def biggest_movers(payload: Dict, board: List[str], meta, n: int = 3) -> Dict:
    """For the landing page: who moved the most, either way, by the end."""
    open_rows = payload["frames"][0]["rows"]
    final_rows = payload["frames"][-1]["rows"]
    deltas = []
    for pid in board:
        row = final_rows.get(pid)
        if row is None:
            continue
        deltas.append((pid, row["price"] - open_rows[pid]["price"]))
    deltas.sort(key=lambda t: t[1])
    losers = [d for d in deltas[:n] if d[1] < 0]
    gainers = [d for d in reversed(deltas[-n:]) if d[1] > 0]
    fmt = lambda pid, d: {
        "name": meta.get(pid, {}).get("name", pid),
        "delta": d,
        "price": final_rows[pid]["price"],
    }
    return {
        "gainers": [fmt(pid, d) for pid, d in gainers],
        "losers": [fmt(pid, d) for pid, d in losers],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("season", type=int, nargs="?", default=LEAGUE_CONFIG.season)
    parser.add_argument("--window", choices=sorted(POINTS_COLUMNS), default="season")
    parser.add_argument("--picks", type=int, default=60)
    parser.add_argument(
        "--w-floor",
        type=float,
        default=1.0,
        help="1.0 = pure VORP, no blending toward the last-rostered bar (default)",
    )
    parser.add_argument(
        "--scenario",
        choices=["all"] + sorted(SCENARIOS),
        default="all",
        help="run one scenario, or 'all' plus the landing page (default)",
    )
    args = parser.parse_args()

    config = LEAGUE_CONFIG
    csv_path = projections_csv_path(args.season)
    players = load_players_from_csv(csv_path, points_column=POINTS_COLUMNS[args.window])
    meta = load_player_meta(csv_path)
    by_id = {p.player_id: p for p in players}
    name_fn = lambda pid: meta.get(pid, {}).get("name", pid)  # noqa: E731

    # The opening board doesn't depend on the scenario -- solve it once and
    # let every scenario start from the same numbers, the same board order,
    # and the same sale sequence. Only the price each sale lands at differs.
    opening_state = LeagueState.opening(config)
    opening = price_board(opening_state, players, config, args.w_floor)
    board = sorted(opening["rows"], key=lambda pid: (-opening["rows"][pid]["price"], pid))
    order = sorted(
        (pid for pid in opening["rows"] if meta.get(pid, {}).get("sleeper_dollar")),
        key=lambda pid: (-meta[pid]["sleeper_dollar"], pid),
    )

    keys = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]
    summaries = []

    for key in keys:
        payload = run_scenario(
            key,
            SCENARIOS[key]["multiplier"],
            config=config,
            players=players,
            meta=meta,
            by_id=by_id,
            order=order,
            opening_rows=opening,
            picks=args.picks,
            w_floor=args.w_floor,
        )
        write_scenario_page(payload, config, args, board, meta, by_id, name_fn)
        movers = biggest_movers(payload, board, meta)
        last = payload["frames"][-1]
        summaries.append(
            {
                "key": key,
                "title": payload["title"],
                "blurb": payload["blurb"],
                "pool_open": payload["frames"][0]["pool"],
                "pool_now": last["pool"],
                "vorp_rate_open": payload["frames"][0]["vorp_rate"],
                "vorp_rate_now": last["vorp_rate"],
                "picks": len(payload["ledger"]),
                "movers": movers,
            }
        )

    if args.scenario == "all":
        index_payload = {
            "season": args.season,
            "league": {"teams": config.teams, "budget": config.budget},
            "picks": args.picks,
            "w_floor": args.w_floor,
            "scenarios": summaries,
        }
        stem = f"draft-demo-{args.season}"
        json_path = REPO_ROOT / "data" / "auction" / f"{stem}.json"
        json_path.write_text(json.dumps(index_payload, indent=2) + "\n")

        template = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")
        fragment = template.replace("__DATA__", json.dumps(index_payload, separators=(",", ":")))
        write_local(fragment, REPO_ROOT / "data" / "auction", stem)
        print(f"Wrote data/{stem}.html -- the landing page, linking to all {len(keys)} scenarios")


if __name__ == "__main__":
    main()
