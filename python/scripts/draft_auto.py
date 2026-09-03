#!/usr/bin/env python3
"""Draft for me, live, from the queue csv -- with the position cap Sleeper's
own queue cannot express.

Sleeper's autopick takes the first available name in the queue, literally, so
a queue with two kickers in it is a roster with two kickers in it. This watches
the board instead: it holds the same ordered list, crosses off what the room
takes, and picks the best remaining player that doesn't break a cap.

The Sleeper queue stays loaded and stays the parachute. This talks to an
undocumented GraphQL endpoint (see draft_pick.py) whose failure mode is a pick
that silently doesn't happen -- so nothing here assumes it works. When a send
is rejected it rings the terminal bell and keeps retrying until the turn ends,
then lets the clock run out into Sleeper's own autopick, which drafts from the
queue exactly as it would have if this were never running.

Fires at the halfway point of the pick clock: late enough to leave a window to
override by hand, early enough not to race Sleeper's autopick at expiry.

Shadow by default -- it logs the pick it would make and sends nothing. `--arm`
sends for real, and needs $SLEEPER_TOKEN.

Usage:
    python scripts/draft_auto.py DRAFT_ID                 # shadow
    python scripts/draft_auto.py DRAFT_ID --arm           # picks for real
    python scripts/draft_auto.py --selftest
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from draft_pick import TOKEN_FILE, build_payload, post, read_token  # noqa: E402
from draft_watch import CAPPED, load_queue  # noqa: E402
from keeper_vorp import pick_schedule  # noqa: E402
from mock_draft import lineup_gaps  # noqa: E402
from vorp.league.config import MY_USERNAME, SNAKE_CONFIG  # noqa: E402
from vorp.sleeper_client import (  # noqa: E402
    API_BASE,
    draft_fingerprint,
    fetch_draft,
    fetch_draft_picks,
)

#: Fraction of the pick clock to let run before sending. 0.5 leaves a manual
#: override window scaled to the timer without racing autopick at expiry.
FIRE_AT = 0.5

#: Fallback when a draft's settings carry no pick_timer (or set it to 0,
#: which Sleeper uses for "no clock").
DEFAULT_PICK_TIMER = 60


def my_user_id(username: str = MY_USERNAME) -> str:
    """Sleeper's public user lookup. Needed because a mock draft has no
    league, so `fetch_league_users` has nothing to resolve a handle against.
    """
    import json

    with urllib.request.urlopen(f"{API_BASE}/user/{username}") as response:
        return str(json.loads(response.read())["user_id"])


def my_slot(draft: dict, username: str = MY_USERNAME) -> int | None:
    """My 1-indexed draft slot from `draft_order` (`{user_id: slot}`).

    `seat_identity` in sleeper_client does the richer version of this, but it
    wants a league user list to map handles to ids and a mock draft has no
    league -- so this resolves the id through the public user endpoint instead.
    """
    order = draft.get("draft_order")
    if not isinstance(order, dict):
        return None
    slot = order.get(my_user_id(username))
    return int(slot) if slot is not None else None


def slot_of_pick(pick_no: int, rounds: int) -> int | None:
    """Which slot owns `pick_no`, via the schedule keeper_vorp already builds.

    `pick_schedule` runs to `roster_size` rounds (16 for SNAKE_CONFIG) while
    the draft itself is `settings.rounds` (15), so the tail is truncated --
    otherwise a finished draft reports a phantom extra round of picks.
    """
    schedule = [p for p in pick_schedule([], 0, SNAKE_CONFIG) if p["round"] <= rounds]
    if 1 <= pick_no <= len(schedule):
        return schedule[pick_no - 1]["slot"]
    return None


def must_fill(roster: Counter, caps: dict[str, int], picks_left: int) -> list[str]:
    """Capped positions that will go unfilled unless taken with the picks that
    remain -- `picks_left` counts this pick.

    Without this the cap is one-sided. A first mock finished 2QB/5RB/3TE/5WR
    and *zero* K or DEF: the queue rates them below every skill player, and the
    draft ran out before the board did, so their slots in the queue were never
    reached. A cap that stops a second kicker but never buys the first is worse
    than no rule at all -- it trades a wasted pick for an unfieldable lineup.
    """
    unfilled = [p for p, need in caps.items() if roster[p] < need]
    return unfilled if len(unfilled) >= picks_left else []


def next_pick(
    queue: list[dict],
    taken: set[str],
    roster: Counter,
    caps: dict[str, int],
    picks_left: int = 10**6,
):
    """First queue entry still available and not at its position cap.

    The cap is the thing the queue itself has no way to say -- and `must_fill`
    is its other half: once there are only as many picks left as mandatory
    slots to fill, the queue's order stops mattering and those positions are
    taken first.

    Returns None when nothing in the queue qualifies -- at which point
    Sleeper's own rankings take over, same as if the queue had run dry.
    """
    forced = must_fill(roster, caps, picks_left)
    for row in queue:
        if row["player_id"] in taken:
            continue
        if forced:
            if row["position"] in forced:
                return row
            continue
        if roster[row["position"]] >= caps.get(row["position"], 10**6):
            continue
        return row
    return None


def should_fire(
    status: str, elapsed_ms: float, pick_timer: int, fire_after: float | None = None
) -> bool:
    """True once the clock has run past `FIRE_AT` of the pick timer, or past a
    flat `fire_after` seconds when one is given.

    A paused draft never fires: the clock isn't running, so "halfway" is
    meaningless and a pick sent into a pause is rejected anyway.
    """
    if status != "drafting":
        return False
    if fire_after is not None:
        return elapsed_ms >= fire_after * 1000
    return elapsed_ms >= (pick_timer or DEFAULT_PICK_TIMER) * 1000 * FIRE_AT


def next_pick_no(taken_nos: set[int], rounds: int) -> int:
    """The lowest pick number nobody has used yet.

    Not `len(picks) + 1`: a keeper draft starts with picks already on the board
    at the round each keeper was kept in, scattered and non-contiguous (18
    keepers over picks 17-108 while the draft was still `pre_draft`). Counting
    them put the board at pick 19 before a single live pick had been made, so
    the slot lookup pointed at the wrong team and my own turn never fired. With
    no keepers the picks run 1..N and this returns `len(picks) + 1` anyway.
    """
    total = rounds * SNAKE_CONFIG.teams
    return next((n for n in range(1, total + 1) if n not in taken_nos), total + 1)


def my_picks_left(
    pick_no: int, slot: int, rounds: int, taken_nos: frozenset[int] = frozenset()
) -> int:
    """How many picks I have from `pick_no` onward, counting it if it's mine.

    `taken_nos` drops the ones a keeper already spent -- otherwise the count is
    inflated and `must_fill` waits too long to force the mandatory positions.
    """
    schedule = [p for p in pick_schedule([], 0, SNAKE_CONFIG) if p["round"] <= rounds]
    return sum(
        1
        for p in schedule
        if p["pick_no"] >= pick_no and p["slot"] == slot and p["pick_no"] not in taken_nos
    )


def retry_due(now: float, last: float | None, retry_every: float) -> bool:
    """Whether a send may be attempted. The first attempt for a pick is always
    due; a rejected one waits `retry_every` before going again.
    """
    return last is None or now - last >= retry_every


def roster_of(picks: list[dict], slot: int) -> Counter:
    mine = [p for p in picks if p.get("draft_slot") is not None and int(p["draft_slot"]) == slot]
    return Counter((p.get("metadata") or {}).get("position") for p in mine)


def run(
    draft_id: str,
    slot: int | None,
    every: float,
    armed: bool,
    token: str | None,
    retry_every: float = 5.0,
    fire_after: float | None = None,
) -> None:
    queue = load_queue(SNAKE_CONFIG.season)
    caps = {p: SNAKE_CONFIG.starting_slots[p] for p in CAPPED}
    sent: set[int] = set()  # pick_no we have already sent for -- never twice
    attempts: dict[int, float] = {}  # pick_no -> monotonic time of last send
    last_seen = -1
    fingerprint = None
    picks: list[dict] = []
    errors = 0

    while True:
        # The cheap/expensive split, same as draft_board.py's poll_sleeper_once:
        # one `/draft` call per tick, and only a `/picks` refetch when the
        # fingerprint moves. Two requests every tick gets rate-limited -- a
        # 1s loop fetching both draws sustained 500s from Sleeper within
        # seconds, while the same loop at one request holds fine.
        #
        # This is only safe for a snake draft because `draft_fingerprint` now
        # includes `last_picked`; on the auction-metadata-only version it would
        # never move here and picks would never refetch.
        try:
            draft = fetch_draft(draft_id)
            current = draft_fingerprint(draft)
            if current != fingerprint:
                fingerprint = current
                picks = fetch_draft_picks(draft_id)
            errors = 0
        except Exception as exc:  # noqa: BLE001 -- a poller that dies on one
            errors += 1  # hiccup is useless
            print(f"poll: {exc}", file=sys.stderr)
            time.sleep(every * min(errors, 5))  # back off rather than hammer
            continue

        settings = draft.get("settings") or {}
        rounds = int(settings.get("rounds") or SNAKE_CONFIG.roster_size)
        pick_timer = int(settings.get("pick_timer") or 0)
        status = draft.get("status") or ""
        if slot is None:
            slot = my_slot(draft)
            if slot is None:
                sys.exit("could not resolve my draft slot -- pass --slot")

        taken_nos = {int(p["pick_no"]) for p in picks if p.get("pick_no") is not None}
        pick_no = next_pick_no(taken_nos, rounds)
        taken = {str(p.get("player_id")) for p in picks}
        roster = roster_of(picks, slot)

        if len(picks) != last_seen:
            last_seen = len(picks)
            # lineup_gaps only knows QB/RB/WR/TE -- mock_draft models the skill
            # lineup and leaves K/DEF out. Reporting its answer alone printed
            # "gaps: none" over a roster with no kicker and no defense, so the
            # capped slots are checked here too -- but only the ones it misses,
            # or capping QB/TE would list them twice.
            gaps = lineup_gaps(roster)
            gaps += [p for p, n in caps.items() if roster[p] < n and p not in gaps]
            have = ", ".join(f"{n}{p}" for p, n in sorted(roster.items())) or "none"
            print(f"pick {pick_no} | {status} | mine: {have} | gaps: {gaps or 'none'}", flush=True)

        if pick_no > rounds * SNAKE_CONFIG.teams:
            print("draft complete", flush=True)
            return

        if slot_of_pick(pick_no, rounds) == slot and pick_no not in sent:
            elapsed = time.time() * 1000 - float(draft.get("last_picked") or 0)
            # Retries are throttled separately from the poll. Polling stays at
            # `every` so the half-clock moment isn't missed, but a rejected send
            # waits `retry_every` before trying again -- a failing pick retried
            # once a second just hammers whatever is already refusing it.
            due = retry_due(time.monotonic(), attempts.get(pick_no), retry_every)
            if should_fire(status, elapsed, pick_timer, fire_after) and due:
                target = next_pick(
                    queue,
                    taken,
                    roster,
                    caps,
                    my_picks_left(pick_no, slot, rounds, frozenset(taken_nos)),
                )
                if target is None:
                    print("queue exhausted -- deferring to Sleeper", flush=True)
                    sent.add(pick_no)
                elif not armed:
                    print(f"SHADOW would pick {target['player']} ({target['position']}) at {pick_no}", flush=True)
                    sent.add(pick_no)
                else:
                    attempts[pick_no] = time.monotonic()
                    try:
                        result = post(build_payload(draft_id, target["player_id"], pick_no), token)
                        if result.get("errors"):
                            raise RuntimeError(result["errors"])
                        sent.add(pick_no)
                        print(f"PICKED {target['player']} ({target['position']}) at {pick_no}", flush=True)
                    except Exception as exc:  # noqa: BLE001 -- retry in retry_every
                        print(f"\aPICK REJECTED at {pick_no}: {exc} (retrying in {retry_every:g}s)",
                              file=sys.stderr, flush=True)

        time.sleep(every)


def selftest() -> None:
    queue = [
        {"player_id": "1", "player": "Gibbs", "position": "RB"},
        {"player_id": "2", "player": "Butker", "position": "K"},
        {"player_id": "3", "player": "Shrader", "position": "K"},
        {"player_id": "4", "player": "Nabers", "position": "WR"},
        {"player_id": "5", "player": "Bowers", "position": "TE"},
        {"player_id": "6", "player": "Allen", "position": "QB"},
    ]
    caps = {"K": 1, "DEF": 1}

    # Skips what the room already took.
    assert next_pick(queue, {"1"}, Counter(), caps)["player"] == "Butker"
    # The whole point: one kicker rostered, the second is passed over.
    assert next_pick(queue, {"1"}, Counter({"K": 1}), caps)["player"] == "Nabers"
    # Uncapped positions are never blocked, however many I have.
    assert next_pick(queue, set(), Counter({"RB": 9}), caps)["player"] == "Gibbs"
    # Exhausted queue defers rather than raising.
    assert next_pick(queue, {"1", "2", "3", "4", "5", "6"}, Counter(), caps) is None

    # The live rule: QB and TE are capped at one alongside K and DEF, so a
    # roster already holding them falls through to the uncapped RB/WR pile.
    full = {p: 1 for p in CAPPED}
    assert next_pick(queue, {"1"}, Counter({"K": 1, "TE": 1}), full)["player"] == "Nabers"
    assert next_pick(queue, {"1", "4"}, Counter({"K": 1, "QB": 1}), full)["player"] == "Bowers"
    # Nothing left but capped positions I've already filled.
    assert next_pick(queue, {"1", "4"}, Counter({"K": 1, "QB": 1, "TE": 1}), full) is None

    # The floor: with picks to spare the queue's order wins and the kicker
    # waits, but once picks_left is down to the mandatory slots it is forced --
    # this is the bug a full mock exposed, finishing 15 deep with no K or DEF.
    assert next_pick(queue, set(), Counter(), caps, picks_left=9)["player"] == "Gibbs"
    assert next_pick(queue, set(), Counter({"DEF": 1}), caps, picks_left=1)["player"] == "Butker"
    assert must_fill(Counter(), {"K": 1, "DEF": 1}, picks_left=2) == ["K", "DEF"]
    assert must_fill(Counter(), {"K": 1, "DEF": 1}, picks_left=3) == []
    assert must_fill(Counter({"K": 1, "DEF": 1}), {"K": 1, "DEF": 1}, picks_left=1) == []
    # With four capped positions the forcing window is four picks wide, not two.
    assert must_fill(Counter(), full, picks_left=4) == ["QB", "TE", "K", "DEF"]
    assert must_fill(Counter(), full, picks_left=5) == []
    # An empty QB slot with one pick left outranks the queue's top RB.
    assert next_pick(queue, set(), Counter({"TE": 1, "K": 1, "DEF": 1}), full, 1)["player"] == "Allen"

    # Picks remaining from a given pick_no, counting it when it is mine.
    assert my_picks_left(7, 7, 15) == 15
    assert my_picks_left(8, 7, 15) == 14
    assert my_picks_left(147, 7, 15) == 1
    # A keeper already spent one of my slots, so it no longer counts as a pick
    # I still get to make.
    assert my_picks_left(7, 7, 15, frozenset({14})) == 14

    # Keeper drafts: picks land on the board before the draft starts, at the
    # round each was kept in, so pick numbers are scattered rather than 1..N.
    assert next_pick_no(set(), 15) == 1  # nothing kept, nothing drafted
    assert next_pick_no({1, 2, 3}, 15) == 4  # ordinary contiguous progress
    # The real shape: 18 keepers over picks 17-108 with the draft not started.
    # len(picks) + 1 would say 19; the board is actually still on pick 1.
    assert next_pick_no({17, 31, 36, 47, 49, 89, 108}, 16) == 1
    assert next_pick_no({1, 2, 17, 31}, 16) == 3  # live picks fill from the front
    assert next_pick_no(set(range(1, 151)), 15) == 151  # exhausted -> past the end

    # Fires at the halfway mark, not before, and never while paused.
    assert not should_fire("drafting", 4_000, 10)
    assert should_fire("drafting", 5_000, 10)
    assert not should_fire("paused", 9_000, 10)
    # No pick_timer in settings falls back rather than firing instantly.
    assert not should_fire("drafting", 1_000, 0)
    assert should_fire("drafting", 31_000, 0)
    # --fire-after replaces the fraction with a flat wait, so a long mock clock
    # doesn't make a 15-round test run take a quarter of an hour of waiting.
    assert not should_fire("drafting", 4_000, 120, fire_after=5)
    assert should_fire("drafting", 5_000, 120, fire_after=5)
    assert not should_fire("paused", 9_000, 120, fire_after=5)

    # First attempt goes immediately; a rejected one waits out retry_every.
    assert retry_due(100.0, None, 5.0)
    assert not retry_due(103.0, 100.0, 5.0)
    assert retry_due(105.0, 100.0, 5.0)

    # Snake order, and the tail truncated to the draft's real round count.
    assert slot_of_pick(1, 15) == 1
    assert slot_of_pick(10, 15) == 10
    assert slot_of_pick(11, 15) == 10  # round 2 reverses
    assert slot_of_pick(141, 15) == 1  # round 15 is odd, so forward again
    assert slot_of_pick(150, 15) == 10
    assert slot_of_pick(151, 15) is None  # 16th round doesn't exist
    print("ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft_id", nargs="?")
    parser.add_argument("--slot", type=int, help="my draft slot; default: from draft_order")
    parser.add_argument("--every", type=float, default=1.0, help="poll interval")
    parser.add_argument(
        "--retry-every", type=float, default=5.0, help="seconds between retries of a rejected pick"
    )
    parser.add_argument("--arm", action="store_true", help="actually send picks")
    parser.add_argument(
        "--fire-after",
        type=float,
        help="seconds into my turn to send, overriding the FIRE_AT fraction. "
        "For testing against a mock, where waiting out half a 2-minute clock "
        "on all 15 picks is the slowest part of the run.",
    )
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.draft_id:
        parser.error("draft_id is required")

    token = read_token()
    if args.arm and not token:
        sys.exit(f"--arm needs a token: set $SLEEPER_TOKEN or write {TOKEN_FILE}")
    if not args.arm:
        print("SHADOW MODE -- no picks will be sent. --arm to go live.", flush=True)

    run(args.draft_id, args.slot, args.every, args.arm, token, args.retry_every, args.fire_after)


if __name__ == "__main__":
    main()
