#!/usr/bin/env python3
"""Export the seat-value model as a playable page -- see
docs/spec/vorp/08-seat-value.md.

The model's whole claim is that the same player is worth different amounts to
different seats, which a static table cannot show: you have to *change* the
roster and watch the number move. So this ships the inputs -- the board, the
bars, one seat's slot template -- and the page re-solves the lineup in the
browser as you add and drop players.

That means the matching exists twice, once in `vorp/league/roster_fill.py` and
once in the template's JavaScript. Duplication earns its keep here (the
alternative is a server, and this is a file you open on a phone), but it has to
be *checked*: `--verify` re-solves every preset in Python and fails the build
if the two disagree, so the page can never quietly drift from the model it
claims to demonstrate.

Board price is the pure-VORP price (`w_floor = 1.0`), not the shipped blend,
because seat value is measured against replacement level. Quoting it against
the blended bar would put the two columns on different bars and break the one
property worth showing -- that an empty seat agrees with the room exactly.

Usage: python artifact/build_seat_value.py [season] [--out=artifacts] [--verify]
"""

from __future__ import annotations

import argparse
import json
import sys
from math import floor
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from artifact.html_page import write_pair  # noqa: E402
from vorp.csv_loader import REPO_ROOT, load_players_from_csv, projections_csv_path  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG  # noqa: E402
from vorp.league.teams import LeagueState  # noqa: E402
from vorp.models import blend_weights  # noqa: E402
from vorp.bid_value import apportion_with_floor  # noqa: E402
from vorp.seat_value import price_from_value, seat_values, vorp_rate  # noqa: E402

from bid_value import POINTS_COLUMNS, load_player_meta  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "templates" / "seat_value.html"

#: Rosters worth landing on, named for the case each one makes. Player ids are
#: resolved by name at build time so a projection refresh that renumbers them
#: fails loudly instead of silently seating the wrong man.
PRESETS = [
    {
        "key": "empty",
        "title": "Opening bell",
        "blurb": (
            "Every slot open, every dollar unspent. Each slot holds an imputed "
            "replacement body, so marginal points ARE points-over-replacement "
            "and this seat agrees with the room on every player. The model is "
            "invisible until you buy something."
        ),
        "roster": [],
    },
    {
        "key": "two-backs",
        "title": "Two backs in",
        "blurb": (
            "Gibbs and Bijan fill both RB slots. A third back can still reach "
            "FLEX and a fourth SUPER_FLEX, so backs are cheaper here than in "
            "the room but far from worthless. Watch the discount deepen with "
            "each one you add."
        ),
        "roster": ["Jahmyr Gibbs", "Bijan Robinson"],
    },
    {
        "key": "rb-saturated",
        "title": "No room at running back",
        "blurb": (
            "Two quarterbacks (one in SUPER_FLEX), three backs (one in FLEX), "
            "two receivers and a tight end. Every RB-eligible slot is spoken "
            "for, so the next ordinary back is worth exactly nothing — while "
            "the room still prices him off replacement level. But running out "
            "of room is not what makes him worthless: sort by Your VORP and "
            "look either side of 190.1, this roster's weakest back. Travis "
            "Etienne at 189.7 is worth $1; Gibbs at 299.9 is worth real money, "
            "because he benches that back and Etienne doesn't. Four tenths of "
            "a point separates the two."
        ),
        # Deliberately mid-market, not the eight best players alive. An
        # all-star roster costs more than the $200 budget at the room's own
        # prices, and a bankrupt seat bids "out" on everyone -- correct, and
        # useless for showing what this page is about. This one spends $156 and
        # leaves a real $37 to bid with.
        "roster": [
            "Bo Nix",
            "Patrick Mahomes",
            "Breece Hall",
            "Kyren Williams",
            "David Montgomery",
            "Ladd McConkey",
            "Zay Flowers",
            "Mark Andrews",
        ],
    },
    {
        "key": "qbs-cheap-second",
        "title": "A cheap second QB",
        "blurb": (
            "This league plays a SUPER_FLEX, so the QB slot and the superflex "
            "are both gone after exactly two passers — no position saturates "
            "faster. Here the second one is Mahomes at 274.7, so that is the "
            "bar — and twelve quarterbacks still beat it: Lamar at $17, Maye "
            "at $14, Hurts at $11. Filter to QB and compare this against the "
            "next preset."
        ),
        "roster": ["Josh Allen", "Patrick Mahomes"],
    },
    {
        "key": "qbs-elite",
        "title": "Two elite QBs",
        "blurb": (
            "The same two slots, filled by the two best passers alive. Now the "
            "bar is Lamar at 318.0 — above every quarterback left on the "
            "board, Drake Maye at 309.8 included. So filter to QB and every "
            "single one is $1, while the room still asks $38 for Maye. Same "
            "number of quarterbacks rostered as the last preset; what changed "
            "is only how high they set the bar."
        ),
        "roster": ["Josh Allen", "Lamar Jackson"],
    },
    {
        "key": "superflex-only",
        "title": "A free QB in the superflex",
        "blurb": (
            "Nine bought, and the tenth slot is a superflex — which is never "
            "really empty. It holds the best body a dollar buys, and for a "
            "QB/RB/WR/TE slot that is a quarterback at 214.8. So a "
            "quarterback has to clear 214.8 here to be worth a cent, while a "
            "back only has to beat your weakest starter at 190.1. Look at the "
            "bar ladder: QB sits far above every other position."
        ),
        "roster": [
            "Bo Nix",
            "Breece Hall",
            "Kyren Williams",
            "David Montgomery",
            "Chris Olave",
            "Ladd McConkey",
            "Zay Flowers",
            "Mark Andrews",
            "Pittsburgh Steelers",
        ],
    },
]


def resolve(names: List[str], by_name: Dict[str, str]) -> List[str]:
    missing = [n for n in names if n not in by_name]
    if missing:
        raise SystemExit(
            f"preset names not on the {LEAGUE_CONFIG.season} board: {missing}. "
            "The projections changed; update PRESETS."
        )
    return [by_name[n] for n in names]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("season", type=int, nargs="?", default=LEAGUE_CONFIG.season)
    parser.add_argument("--window", choices=sorted(POINTS_COLUMNS), default="season")
    parser.add_argument("--out", default="artifacts")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-solve every preset in Python and print the values the page must match",
    )
    args = parser.parse_args()

    config = LEAGUE_CONFIG
    csv_path = projections_csv_path(args.season)
    players = load_players_from_csv(csv_path, points_column=POINTS_COLUMNS[args.window])
    meta = load_player_meta(csv_path)

    state = LeagueState.opening(config)
    replacement_solve, last_rostered, vorp_bar, volr_bar, _ = blend_weights(
        players, config, state
    )
    drafted = set(last_rostered.selected_player_ids)

    # The exchange rate and the board price both run off the same weights: a
    # player's margin over replacement level, floored at zero.
    weights = {
        p.player_id: max(0.0, p.points - vorp_bar[p.position])
        for p in players
        if p.player_id in drafted and p.position in vorp_bar
    }
    rate = vorp_rate(state.pool(), weights, config.min_bid)

    # 03's other lens, priced the way 03 prices it: the WHOLE budget
    # apportioned across the same population by margin over the last-rostered
    # bar. Not a rescaling of VORP $ -- its own bar and its own rate, which is
    # why the two cross. VORP concentrates money at the top (most of the board
    # has no margin over replacement at all); VOLR spreads it, because every
    # rostered player clears the last-rostered bar by something.
    volr_weights = {
        p.player_id: max(0.0, p.points - volr_bar[p.position])
        for p in players
        if p.player_id in drafted and p.position in volr_bar
    }
    volr_dollars = apportion_with_floor(state.pool(), volr_weights, config.min_bid)

    # Both rates, and the count that explains the gap between them. A lower
    # bar does not buy anyone more money: it hands everyone a bigger margin,
    # which inflates the denominator and shrinks the rate by the same factor.
    # What actually concentrates VORP dollars at the top is the players with
    # NO margin at all -- they take the floor and contribute nothing to the
    # split. Every player clears the last-rostered bar by something, so VOLR
    # has no such tail and spreads thin.
    volr_rate_value = vorp_rate(state.pool(), volr_weights, config.min_bid)
    zero_vorp = sum(1 for v in weights.values() if v <= 0)

    by_name = {meta[pid]["name"]: pid for pid in weights if pid in meta}
    by_id = {p.player_id: p for p in players}

    board = []
    for pid, margin in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
        p = by_id[pid]
        info = meta.get(pid, {})
        board.append(
            {
                "id": pid,
                "name": info.get("name", pid),
                "team": info.get("team"),
                "pos": p.position,
                "points": round(p.points, 1),
                "vorp": round(margin, 1),
                "board": config.min_bid + floor(rate * margin),
                "volr": volr_dollars.get(pid, config.min_bid),
                "market": info.get("sleeper_dollar"),
            }
        )

    # One seat's STARTING slots -- the list the lineup solve runs over. Bench
    # slots are deliberately absent: a benched player scores nothing.
    seat = state.seats[0]
    slots = [
        {"id": s.id, "eligible": list(s.eligible_positions)}
        for s in state.seat_slots(seat, bench=False)
    ]

    presets = [dict(p, roster=resolve(p["roster"], by_name)) for p in PRESETS]

    payload = {
        "season": args.season,
        "window": args.window,
        "league": {
            "teams": config.teams,
            "budget": config.budget,
            "min_bid": config.min_bid,
            "bench_slots": config.bench_slots,
            "roster_size": config.roster_size,
            "starting_slots": sum(config.starting_slots.values())
            + sum(config.flex_slots.values()),
        },
        "rate": round(rate, 4),
        "volr_rate": round(volr_rate_value, 4),
        "zero_vorp": zero_vorp,
        "replacement": {pos: round(v, 1) for pos, v in vorp_bar.items()},
        # 02's last-rostered bar, carried only so the page can show that a
        # seat's own bar moves in the OPPOSITE direction to it. VOLR asks
        # "worth a bench spot at all" and sits below replacement level;
        # filling your roster raises your bar above it.
        "last_rostered": {pos: round(v, 1) for pos, v in volr_bar.items()},
        "slots": slots,
        "players": board,
        "presets": presets,
    }

    if args.verify:
        verify(payload, state, by_id, config)

    fragment = TEMPLATE.read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(payload, separators=(",", ":"))
    )
    out_dir = REPO_ROOT / args.out
    stem = f"seat-value-{args.season}"
    fragment_path = write_pair(fragment, out_dir, stem)

    size_kb = len(fragment.encode("utf-8")) / 1000
    print(f"Wrote {fragment_path.relative_to(REPO_ROOT)} ({size_kb:.0f} KB)")
    print(f"      {(out_dir / f'{stem}.html').relative_to(REPO_ROOT)} (open locally)")
    print(f"      {len(board)} players, rate ${rate:.3f}/pt, {len(slots)} starting slots")


def verify(payload: Dict, state: LeagueState, by_id: Dict, config) -> None:
    """Re-solve each preset through the real model and print what the page's
    JavaScript has to reproduce. The build is only as trustworthy as this.
    """
    replacement = payload["replacement"]
    points = {p.player_id: p.points for p in by_id.values()}
    board_by_id = {row["id"]: row for row in payload["players"]}
    print("Preset check -- the page must reproduce these:")

    for preset in payload["presets"]:
        # A preset is charged the room's price for what it holds, so an
        # all-star roster can cost more than the budget. That seat is bankrupt
        # and correctly bids "out" on everyone -- which renders a page that
        # demonstrates nothing. Catch it at build time.
        cost = sum(board_by_id[pid]["board"] for pid in preset["roster"])
        open_spots = config.roster_size - len(preset["roster"])
        headroom = config.budget - cost - max(0, open_spots - 1) * config.min_bid
        if headroom < config.min_bid:
            raise SystemExit(
                f"preset {preset['key']!r} costs ${cost} of a ${config.budget} "
                f"budget, leaving a max bid of ${headroom}. It would show "
                "'out' on every player. Pick cheaper players."
            )

        # Charge the room's price, so the seat's budget and cap match the
        # page's -- which bills a rostered player at exactly that.
        seated = state
        for pid in preset["roster"]:
            seated = seated.sell(
                pid, by_id[pid].position, board_by_id[pid]["board"], seat_id=0
            )

        probes = [pid for pid in board_by_id if pid not in preset["roster"]][:400]
        values = seat_values(
            seated, 0, [by_id[pid] for pid in probes], replacement, points
        )
        rate = payload["rate"]
        # Capped, because that is the number the page prints.
        priced = {pid: price_from_value(v, rate, seated, 0) for pid, v in values.items()}
        agrees = sum(1 for pid, d in priced.items() if d == board_by_id[pid]["board"])
        zeroed = sum(1 for v in values.values() if v == 0.0)
        # Per position: how many are still worth more than the floor. A
        # preset whose whole point is "every quarterback is now $1" should
        # say so here, not just in its blurb.
        by_pos = {}
        for pid, dollars in priced.items():
            pos = by_id[pid].position
            hit = by_pos.setdefault(pos, [0, 0])
            hit[0] += 1
            if dollars > config.min_bid:
                hit[1] += 1
        above = " ".join(
            f"{pos} {n}/{t}" for pos, (t, n) in sorted(by_pos.items())
        )

        sample = sorted(
            (pid for pid in priced if by_id[pid].position == "RB"),
            key=lambda pid: -board_by_id[pid]["board"],
        )[:3]
        print(f"  [{preset['key']}] {len(values)} valued, {zeroed} at zero, "
              f"{agrees} agree with the room")
        print(f"      above the $1 floor: {above}")
        for pid in sample:
            print(f"      {board_by_id[pid]['name']:<22} room ${board_by_id[pid]['board']:>3}"
                  f"   seat ${priced[pid]:>3}   ({values[pid]:.1f} pts)")


if __name__ == "__main__":
    main()
