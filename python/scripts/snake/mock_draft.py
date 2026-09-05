#!/usr/bin/env python3
"""Mock the snake draft against my actual queue, many times, and report what
roster it actually hands me.

The queue is a static list but the draft is not: the nine other seats take
players off the board between my turns, so what I end up with is a
*subsequence* of the queue, and which subsequence depends on how the room
drafts. One mock tells me almost nothing. A few hundred tells me the shape of
the distribution -- how often I finish with no tight end, how deep into the
queue I get, whether a position runs away with my roster.

Room model: every seat but mine drafts by ADP with per-draft noise, so a
player's board position is consistent within one mock but varies across them.
Sigma is in ADP-picks; 10 is roughly the spread you see between a consensus
board and where players actually go.

My seat takes the first still-available player in the queue -- exactly what
Sleeper's autopick does. If the queue empties, Sleeper falls back to its own
rankings, approximated here as best-available by ADP.

Usage: python scripts/mock_draft.py [season] [--runs 500] [--sigma 10] [--seed N]
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from keeper_vorp import load_keepers, pick_schedule  # noqa: E402
from queue_export import load_board, load_manual, load_my_keepers  # noqa: E402
from vorp.league.config import MY_USERNAME, SNAKE_CONFIG  # noqa: E402

#: ADP-picks of noise on each player's board position, resampled per mock.
DEFAULT_SIGMA = 10.0

#: Players the board has no ADP for go at the very end, in VORP order. Without
#: this they'd sort as if they were the first pick.
NO_ADP = 10_000.0

#: The starting lineup a finished roster has to be able to field. FLEX takes
#: RB/WR/TE, so it's checked against the leftovers rather than by position.
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
FLEX_SLOTS = 2


def load_queue(season: int) -> list[str]:
    import csv

    path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "snake" / f"queue-snake-{season}.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return [row["player"] for row in csv.DictReader(f)]


def run_one(board, queue, keepers, my_slot, config, rng, sigma):
    """One mock. Returns (my roster as position list, queue depth reached)."""
    kept = {k["player_name"] for k in keepers}
    pool = {r["player"]: r for r in board if r["player"] not in kept}

    # Per-draft board: ADP plus noise, so the room is consistent within a mock.
    noisy = {
        name: (float(r["adp"]) if r["adp"] else NO_ADP) + rng.gauss(0, sigma)
        for name, r in pool.items()
    }
    by_adp = sorted(pool, key=lambda n: noisy[n])

    mine: list[dict] = []
    depth = 0
    for pick in pick_schedule(keepers, my_slot, config):
        if pick["is_keeper"]:
            continue
        if pick["mine"]:
            # Autopick: first still-available player in the queue.
            taken = next((n for n in queue[depth:] if n in pool), None)
            if taken is not None:
                depth = queue.index(taken) + 1
            else:  # queue exhausted -> Sleeper's own board
                taken = next((n for n in by_adp if n in pool), None)
            if taken is None:
                break
            mine.append(pool.pop(taken))
        else:
            taken = next((n for n in by_adp if n in pool), None)
            if taken is None:
                break
            pool.pop(taken)
    return mine, depth


def lineup_gaps(positions: Counter) -> list[str]:
    """Starting slots this roster cannot fill. FLEX is checked last, against
    whatever RB/WR/TE are left after the concrete slots are covered.
    """
    gaps = [p for p, need in STARTERS.items() for _ in range(max(0, need - positions[p]))]
    spare = sum(max(0, positions[p] - STARTERS[p]) for p in ("RB", "WR", "TE"))
    gaps += ["FLEX"] * max(0, FLEX_SLOTS - spare)
    return gaps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", nargs="?", type=int, default=SNAKE_CONFIG.season)
    parser.add_argument("--runs", type=int, default=500)
    parser.add_argument("--sigma", type=float, default=DEFAULT_SIGMA)
    parser.add_argument("--seed", type=int, default=20260901)
    opts = parser.parse_args()
    season, runs, sigma, seed = opts.season, opts.runs, opts.sigma, opts.seed

    # Kickers stay in the *room's* pool even though they're off my queue --
    # the other nine seats still draft one eventually. Defenses have to be
    # added on top: they are absent from the VORP board entirely, so without
    # this the room never drafts one, every defense in my queue is permanently
    # "available", and the mock cannot see the cost of queueing them.
    board = load_board(season, drafted_by_hand=True)
    seen = {r["player_id"] for r in board}
    board += [r for r in load_manual(season) if r["player_id"] not in seen]
    queue = load_queue(season)
    keepers = load_keepers(season)
    mine = load_my_keepers(season)
    my_slot = next(int(k["draft_slot"]) for k in mine)
    rng = random.Random(seed)

    shapes, depths, gap_counts, rosters = Counter(), [], Counter(), []
    for _ in range(runs):
        roster, depth = run_one(board, queue, keepers, my_slot, SNAKE_CONFIG, rng, sigma)
        pos = Counter(r["position"] for r in roster)
        pos.update(k["position"] for k in mine)  # keepers are on the roster too
        shapes[tuple(sorted(pos.items()))] += 1
        depths.append(depth)
        gaps = lineup_gaps(pos)
        gap_counts.update(gaps or ["(none)"])
        rosters.append((roster, pos, gaps))

    print(f"{runs} mocks, seat {my_slot}, ADP sigma {sigma}, queue {len(queue)} deep")
    print(f"Keeping: " + ", ".join(f"{k['player_name']} ({k['position']})" for k in mine))

    print(f"\nQueue depth reached: median {statistics.median(depths):.0f}, "
          f"min {min(depths)}, max {max(depths)} of {len(queue)}")

    print("\nRoster shape (with keepers), most common:")
    for shape, n in shapes.most_common(5):
        s = "  ".join(f"{p} {c}" for p, c in shape)
        print(f"  {n / runs:>5.0%}  {s}")

    print("\nUnfillable starting slots:")
    for slot, n in gap_counts.most_common():
        print(f"  {slot:<8} {n / runs:>5.0%} of mocks")

    roster, pos, gaps = rosters[0]
    print(f"\nSample mock -- my 14 picks in order:")
    for i, r in enumerate(roster, 1):
        adp = f"{float(r['adp']):.1f}" if r["adp"] else "--"
        print(f"  {i:>3}. {r['player']:<24} {r['position']:<4} adp {adp:>6}  vorp {r['vorp_avg']:>6}")
    print("  shape: " + "  ".join(f"{p} {c}" for p, c in sorted(pos.items())))
    print("  unfillable: " + (", ".join(gaps) if gaps else "none"))


if __name__ == "__main__":
    main()
