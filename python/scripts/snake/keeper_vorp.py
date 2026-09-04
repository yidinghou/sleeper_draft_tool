#!/usr/bin/env python3
"""Keeper-aware VORP for the snake draft pool, averaged across projections.

2026 keepers occupy real roster slots, which shifts where the replacement
and last-rostered bars fall for everyone else. This seeds a LeagueState with
the keepers as pre-draft picks (see docs/spec/league/03-seats-and-sales.md),
then solves the bars against what's actually still open -- once per
projection source (Sleeper, Boberto), since each source needs its own bar to
be comparable, and averages the resulting margins.

Keepers also consume their own pick slots, so rounds are not a flat 10 picks
and the gap between two of my turns varies -- hence the pick schedule at the
bottom.

Usage: python scripts/keeper_vorp.py [season] [--refresh-adp]
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from html_page import write_local  # noqa: E402
from vorp.csv_loader import load_players_from_csv, projections_csv_path, REPO_ROOT  # noqa: E402
from vorp.last_rostered import calculate_last_rostered_levels  # noqa: E402
from vorp.league.config import MY_USERNAME, SNAKE_CONFIG  # noqa: E402
from vorp.league.teams import LeagueState  # noqa: E402
from vorp.replacement_level import calculate_replacement_levels  # noqa: E402

#: The snake league's own draft, exported from Sleeper -- keeper rows carry
#: `draft_slot`, so seats here are the real ones, not an arbitrary mapping.
PICKS_CSV = REPO_ROOT / "data" / "snake" / "snake-draft-2026-picks.csv"

#: Kept off the board entirely. A defense is streamed off waivers all season,
#: so its draft-day value is roughly "whoever is left in the last round" --
#: ranking it against real players just pushes it up the board. Dropping the
#: position doesn't disturb anyone else's bar: DEF's only slot is its own
#: concrete one (no flex takes a defense, and it's already off the bench via
#: STREAMING_POSITIONS), so that slot simply goes unfilled.
EXCLUDE_POSITIONS = ("DEF",)

HTML_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "keeper_vorp.html"

#: Sleeper's own ADP for this league's format. `adp_half_ppr` is the 1QB
#: half-PPR board; the auction league's `sleeper_rank` is the superflex one,
#: which ranks quarterbacks far too high for a snake league that starts one.
#: Sleeper publishes no per-league-size ADP, so this is 1QB half-PPR across
#: all league sizes, not a 10-team number specifically.
ADP_FIELD = "adp_half_ppr"
ADP_URL = "https://api.sleeper.app/v1/projections/nfl/regular/{season}"


def load_adp(season: int, refresh: bool = False) -> dict[str, float]:
    """player_id -> ADP, cached locally so draft day needs no network."""
    cache = REPO_ROOT / "data" / f"adp-{season}.csv"
    if refresh or not cache.exists():
        import urllib.request

        with urllib.request.urlopen(ADP_URL.format(season=season), timeout=30) as response:
            payload = json.load(response)
        # 999 is Sleeper's "undrafted" sentinel, not a real ADP.
        adp = {
            pid: stats[ADP_FIELD]
            for pid, stats in payload.items()
            if stats.get(ADP_FIELD, 999) < 999
        }
        with cache.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["player_id", "adp"])
            writer.writerows(sorted(adp.items(), key=lambda kv: kv[1]))
        print(f"Fetched {len(adp)} {ADP_FIELD} values -> {cache.relative_to(REPO_ROOT)}")

    with cache.open(newline="", encoding="utf-8") as f:
        return {row["player_id"]: float(row["adp"]) for row in csv.DictReader(f)}


def source_csv(name: str, season: int) -> Path:
    return projections_csv_path(season) if name == "sleeper" else REPO_ROOT / "data" / f"{name}-{season}.csv"


def load_keepers(season: int) -> list[dict]:
    with PICKS_CSV.open(newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row["is_keeper"] == "True"]


def build_state(keepers: list[dict], config) -> LeagueState:
    """Keepers as picks already made, seated by their real draft slot."""
    state = LeagueState.opening(config)
    for row in keepers:
        # amount=0: snake draft, no money -- sell() only marks the slot filled.
        state = state.sell(
            row["player_id"], row["position"], amount=0, seat_id=int(row["draft_slot"]) - 1
        )
    return state


def vorp_by_source(source: str, season: int, keepers: list[dict], config) -> dict[str, dict]:
    """VORP and VOLR margins for every non-keeper, off one projection source."""
    players = load_players_from_csv(source_csv(source, season))
    kept = {row["player_id"] for row in keepers}
    remaining = [
        p for p in players if p.player_id not in kept and p.position not in EXCLUDE_POSITIONS
    ]
    state = build_state(keepers, config)

    vorp_bar = {
        pos: s.replacement_level
        for pos, s in calculate_replacement_levels(remaining, config, state).by_position.items()
    }
    volr_bar = {
        pos: s.last_rostered_level
        for pos, s in calculate_last_rostered_levels(remaining, config, state).by_position.items()
    }
    return {
        p.player_id: {
            "points": p.points,
            "vorp": round(p.points - vorp_bar[p.position], 1) if vorp_bar.get(p.position) else None,
            "volr": round(p.points - volr_bar[p.position], 1) if volr_bar.get(p.position) else None,
        }
        for p in remaining
    }


def add_value(rows: list[dict], drafted: int) -> None:
    """VORP against ADP: what a player returns over *par for his draft slot*.

    The two aren't in the same units, so par is read off the board itself --
    the VORP the Nth-best player carries is what the Nth pick is worth. A
    player going Nth by ADP is then a bargain by however much his own VORP
    beats that. Rows must already be sorted by VORP descending.

    `value_rank` is the same comparison in slots rather than points: how many
    picks later he goes than his value says he should. Points catch what
    slots miss -- twenty slots across a cliff is a different thing from
    twenty slots down a flat stretch of the board.

    Only players inside `drafted` get a value at all. Past the last pick
    there is no slot to be a bargain against: measuring a man with an ADP of
    689 against the worst rostered player scores him as a massive steal, when
    what the ADP actually says is that nobody drafts him.
    """
    par = [r["vorp_avg"] for r in rows]
    ranked = sorted((r for r in rows if r["adp"] is not None), key=lambda r: r["adp"])
    board_rank = {id(r): i for i, r in enumerate(rows)}

    for r in rows:
        r["value"] = r["value_rank"] = None
    for adp_rank, r in enumerate(ranked):
        if r["adp"] > drafted or adp_rank >= len(par):
            continue
        r["value"] = round(r["vorp_avg"] - par[adp_rank], 1)
        r["value_rank"] = adp_rank - board_rank[id(r)]


def pick_schedule(keepers: list[dict], my_slot: int, config) -> list[dict]:
    """Every pick in snake order, keeper picks flagged, with how many live
    picks fall between one of my turns and the next.
    """
    kept_pick_nos = {int(row["pick_no"]) for row in keepers}
    picks = []
    for rnd in range(1, config.roster_size + 1):
        order = range(1, config.teams + 1) if rnd % 2 else range(config.teams, 0, -1)
        for i, slot in enumerate(order):
            pick_no = (rnd - 1) * config.teams + i + 1
            picks.append(
                {
                    "pick_no": pick_no,
                    "round": rnd,
                    "slot": slot,
                    "is_keeper": pick_no in kept_pick_nos,
                    "mine": slot == my_slot,
                }
            )

    # Live picks only: a keeper pick takes no player off the open board.
    live = 0
    for pick in picks:
        pick["live_no"] = None if pick["is_keeper"] else (live := live + 1)

    my_live = [p for p in picks if p["mine"] and not p["is_keeper"]]
    for pick, nxt in zip(my_live, my_live[1:]):
        pick["gap"] = nxt["live_no"] - pick["live_no"] - 1
        pick["next_pick_no"] = nxt["pick_no"]
    return picks


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    season = int(args[0]) if args else SNAKE_CONFIG.season
    adp = load_adp(season, refresh="--refresh-adp" in sys.argv)
    keepers = load_keepers(season)
    sources = ("sleeper", "boberto")
    by_source = {s: vorp_by_source(s, season, keepers, SNAKE_CONFIG) for s in sources}

    meta = {
        row["player_id"]: row
        for row in csv.DictReader(projections_csv_path(season).open(newline="", encoding="utf-8"))
    }

    rows = []
    for pid in set().union(*(d.keys() for d in by_source.values())):
        got = {s: d[pid] for s, d in by_source.items() if pid in d and d[pid]["vorp"] is not None}
        if not got:
            continue
        row = meta.get(pid, {})
        rows.append(
            {
                "player_id": pid,
                "player": row.get("player", ""),
                "position": row.get("position", ""),
                "team": row.get("team", ""),
                "adp": adp.get(pid),
                "bye": row.get("bye_week") or "",
                "vorp_avg": round(mean(v["vorp"] for v in got.values()), 1),
                **{f"vorp_{s}": got[s]["vorp"] if s in got else None for s in sources},
                **{f"pts_{s}": got[s]["points"] if s in got else None for s in sources},
                "sources": len(got),
            }
        )
    rows.sort(key=lambda r: -r["vorp_avg"])
    drafted = SNAKE_CONFIG.teams * SNAKE_CONFIG.roster_size
    add_value(rows, drafted)

    out_path = REPO_ROOT / "data" / "snake" / f"vorp-snake-{season}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    both = sum(1 for r in rows if r["sources"] == len(sources))
    print(f"{len(keepers)} keepers excluded, {len(rows)} players ({both} in both sources)\n")
    print(f"  {'#':>3}  {'PLAYER':<24} {'POS':<4} {'TEAM':<5} {'AVG':>7} {'SLEEPER':>8} {'BOBERTO':>8}")
    for i, r in enumerate(rows[:20], 1):
        fmt = lambda v: f"{v:.1f}" if v is not None else "-"  # noqa: E731
        print(
            f"  {i:>3}  {r['player']:<24} {r['position']:<4} {r['team']:<5} "
            f"{r['vorp_avg']:>7.1f} {fmt(r['vorp_sleeper']):>8} {fmt(r['vorp_boberto']):>8}"
        )
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}\n")

    # Best values: most VORP over par for the slot they actually cost. Capped
    # to players inside the drafted range -- a bargain 300 picks deep is one
    # nobody has to reach for.
    # Kickers are left out of the shortlist (they stay in the CSV and on the
    # page). K1 to K11 is ~16 projected points, which the model reads as real
    # VORP and ADP prices at nothing, so kickers sweep any value ranking --
    # but nobody reaches 60 slots for a kicker, because that spread is
    # projection noise, not signal.
    values = sorted(
        (r for r in rows if r["value"] is not None and r["position"] != "K"),
        key=lambda r: -r["value"],
    )
    print(f"Best value vs ADP (top {len(values[:15])}, K excluded, inside pick {drafted}):\n")
    print(f"  {'ADP':>6} {'PLAYER':<24} {'POS':<4} {'VORP':>7} {'VALUE':>7} {'SLOTS':>6}")
    for r in values[:15]:
        print(
            f"  {r['adp']:>6.1f} {r['player']:<24} {r['position']:<4} "
            f"{r['vorp_avg']:>7.1f} {r['value']:>+7.1f} {r['value_rank']:>+6}"
        )
    print()

    my_slot = next(int(r["draft_slot"]) for r in keepers if r["owner"] == MY_USERNAME)
    picks = pick_schedule(keepers, my_slot, SNAKE_CONFIG)
    print(f"Draft slot {my_slot} ({MY_USERNAME}) -- my picks, and who picks between them:\n")
    print(f"  {'RD':>3} {'PICK':>5} {'LIVE':>5}  {'UNTIL MY NEXT':<14} KEEPERS IN BETWEEN")
    my = [p for p in picks if p["mine"]]
    for pick in my:
        if pick["is_keeper"]:
            kept = next(k for k in keepers if int(k["pick_no"]) == pick["pick_no"])
            print(f"  {pick['round']:>3} {pick['pick_no']:>5} {'kept':>5}  {kept['player_name']}")
            continue
        gap = pick.get("gap")
        stop = pick.get("next_pick_no", picks[-1]["pick_no"] + 1)
        between = [
            p for p in picks if pick["pick_no"] < p["pick_no"] < stop and p["is_keeper"]
        ]
        print(
            f"  {pick['round']:>3} {pick['pick_no']:>5} {pick['live_no']:>5}  "
            f"{(f'{gap} picks' if gap is not None else 'last pick'):<14} "
            f"{', '.join(str(p['pick_no']) for p in between) or '-'}"
        )

    print_board_windows(rows, picks, through_round=8)

    payload = {
        "season": season,
        "sources": list(sources),
        "my_slot": my_slot,
        "my_picks": [
            {
                "round": p["round"],
                "pick_no": p["pick_no"],
                "rank": p["live_no"],
                "gap": p.get("gap"),
                "keeper": next(
                    (k["player_name"] for k in keepers if int(k["pick_no"]) == p["pick_no"]), None
                ),
            }
            for p in picks
            if p["mine"]
        ],
        "keepers": [
            {"player": k["player_name"], "position": k["position"], "team_name": k["team_name"]}
            for k in keepers
        ],
        "players": rows,
    }
    template = HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    fragment = template.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    write_local(fragment, REPO_ROOT / "data" / "snake", f"vorp-snake-{season}")
    print(f"\nWrote data/vorp-snake-{season}.html")


def print_board_windows(rows: list[dict], picks: list[dict], through_round: int) -> None:
    """Who sits at my pick on the VORP board, and who's likely gone by my next
    turn. Rank is VORP order, not ADP -- the room does not draft in VORP
    order, so read this as "this tier is where I'm picking", not a prediction
    of who is literally there.
    """
    print(f"\n\nBoard around my picks, rounds 1-{through_round} (rank = VORP order):")
    for pick in picks:
        if not pick["mine"] or pick["round"] > through_round:
            continue
        if pick["is_keeper"]:
            print(f"\n  Round {pick['round']}, pick {pick['pick_no']} -- kept, no selection")
            continue
        at = pick["live_no"]
        window = rows[max(0, at - 3) : at + 2]
        print(f"\n  Round {pick['round']}, pick {pick['pick_no']} (board rank ~{at}):")
        for i, r in enumerate(window, max(1, at - 2)):
            mark = "<<<" if i == at else ""
            print(
                f"    {i:>4}. {r['player']:<24} {r['position']:<4} {r['team']:<5} "
                f"{r['vorp_avg']:>7.1f}  {mark}"
            )


if __name__ == "__main__":
    main()
