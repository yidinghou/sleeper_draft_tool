#!/usr/bin/env python3
"""Watch a live snake draft and tell me what to cut from the queue.

Sleeper's v1 API is read-only -- there is no queue endpoint -- so this can't
edit the queue for me. What it can do is answer the one question that makes me
want to: has a position filled, and which queue entries are now dead weight?
A filled K or DEF slot with more of them still queued is autodraft about to
spend a pick on a backup kicker.

Picks are matched by `player_id`, not name, so nothing depends on Sleeper and
the queue csv spelling a player the same way.

My picks are identified by `draft_slot` (1-indexed, as Sleeper reports it)
rather than by username: the snake league's `league_id` is blank in config, so
there is no user list to resolve a handle against.

Usage: python scripts/draft_watch.py DRAFT_ID --slot N [--season 2026]
                                     [--every 10] [--once] [--selftest]
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.league.config import SNAKE_CONFIG  # noqa: E402
from vorp.sleeper_client import fetch_draft_picks  # noqa: E402

#: Positions autodraft should only ever take once, and how many of each the
#: lineup actually starts. Everything else is flex-eligible and self-limiting.
CAPPED = ("K", "DEF")

#: Still-available queue entries to list each time the board moves.
UPCOMING = 5


def load_queue(season: int) -> list[dict]:
    path = Path(__file__).resolve().parent.parent.parent / "data" / f"queue-snake-{season}.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def report(queue: list[dict], picks: list[dict], my_slot: int, caps: dict[str, int]) -> list[str]:
    """Lines to print for the board as it stands. Pure, so --selftest can
    check it without a draft."""
    gone = {str(p.get("player_id")) for p in picks}
    mine = [p for p in picks if p.get("draft_slot") is not None and int(p["draft_slot"]) == my_slot]
    have = Counter((p.get("metadata") or {}).get("position") for p in mine)

    lines = [f"pick {len(picks) + 1} | mine: " + (", ".join(f"{n}{p}" for p, n in sorted(have.items())) or "none")]

    for position, cap in caps.items():
        if have[position] >= cap:
            dead = [r["player"] for r in queue if r["position"] == position and r["player_id"] not in gone]
            if dead:
                lines.append(f"  CUT {position} ({have[position]}/{cap} rostered): " + ", ".join(dead))

    live = [r for r in queue if r["player_id"] not in gone]
    lines.append("  next: " + (", ".join(f"{r['player']} ({r['position']})" for r in live[:UPCOMING]) or "QUEUE EMPTY"))
    return lines


def selftest() -> None:
    queue = [
        {"player_id": "1", "player": "Gibbs", "position": "RB"},
        {"player_id": "2", "player": "Butker", "position": "K"},
        {"player_id": "3", "player": "Shrader", "position": "K"},
    ]
    picks = [
        {"player_id": "1", "draft_slot": 4, "metadata": {"position": "RB"}},
        {"player_id": "2", "draft_slot": 4, "metadata": {"position": "K"}},
    ]
    out = "\n".join(report(queue, picks, 4, {"K": 1}))
    assert "CUT K (1/1 rostered): Shrader" in out, out
    assert "Butker" not in out, out  # drafted, so neither queued nor cut-worthy
    assert "1K, 1RB" in out, out
    # No kicker yet: nothing to cut.
    assert "CUT" not in "\n".join(report(queue, picks[:1], 4, {"K": 1}))
    # Someone else's kicker doesn't fill my slot.
    assert "CUT" not in "\n".join(report(queue, [{**picks[1], "draft_slot": 7}], 4, {"K": 1}))
    print("ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft_id", nargs="?")
    parser.add_argument("--slot", type=int, help="my draft slot, 1-indexed")
    parser.add_argument("--season", type=int, default=SNAKE_CONFIG.season)
    parser.add_argument("--every", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.draft_id or not args.slot:
        parser.error("draft_id and --slot are required")

    queue = load_queue(args.season)
    caps = {p: SNAKE_CONFIG.starting_slots[p] for p in CAPPED}
    seen = -1
    while True:
        picks = fetch_draft_picks(args.draft_id)
        if len(picks) != seen:
            seen = len(picks)
            print("\n".join(report(queue, picks, args.slot, caps)), flush=True)
        if args.once:
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
