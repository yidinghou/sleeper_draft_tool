#!/usr/bin/env python3
"""The autodraft queue for the snake draft: the VORP board, top to bottom.

Sleeper's autopick takes the top still-available player in the queue, in queue
order, and only falls back to its own rankings when the queue is empty -- and
those rankings still have all 18 keepers on the board. So the queue is the
ranking that actually gets executed, and it should be the ranking I believe:
`vorp_avg`, the average of the Sleeper and Boberto projections.

No positional constraint of any kind. Earlier versions carried a proportional
per-position ceiling to stop autodraft taking five running backs in a row, but
running backs dominate the top of this board, so the cap kept deferring them
and floating worse players up in their place -- Josh Allen (VORP 67.6, 12th on
the board) landed above Derrick Henry (95.8, 7th), and Drake Maye (21.1, 33rd)
reached slot 18. Any rule that promotes a player above his VORP is buying
roster balance with draft value. Balance is handled by picking manually when
it matters instead.

K and DEF are left out and drafted by hand. DEF isn't on the board at all
(keeper_vorp.py's EXCLUDE_POSITIONS). Kickers are excluded because their VORP
is an artifact, not a preference: K1 to K11 is ~16 projected points, which the
model reads as real margin and ranks from ~#41. Nobody else drafts a kicker
early, so every queued kicker survives to my turn and autopick takes it.
scripts/mock_draft.py measures the damage over 400 mocks -- with kickers in a
90-deep queue I average eight of them and finish with a fieldable starting
lineup 4% of the time; without, 92%.

Depth is set where the same mocks stop improving: 90 leaves no unfillable QB
or TE slot, and 120 is no better. A 60-deep queue empties around round 11 and
hands the rest to Sleeper's board.

Reads the finished board rather than re-solving it -- keeper_vorp.py owns the
VORP math and data/vorp-snake-{season}.csv is the contract between them.

Usage: python scripts/queue_export.py [season] [--depth N]
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.csv_loader import REPO_ROOT, projections_csv_path  # noqa: E402
from vorp.league.config import MY_USERNAME, SNAKE_CONFIG  # noqa: E402

#: Where the mocks stop improving -- see the module docstring. Also has to
#: outrun sniping: the queue must not empty, because the fallback is Sleeper's
#: default board, which still has every keeper on it.
#:
#: Deep enough to hold the whole rated pool. K and DEF sit in their ADP rounds,
#: which is the back of it, so a queue that stopped at 90 would rank them in
#: the builder and then never queue them.
DEFAULT_DEPTH = 120

#: Not on the VORP board, so they only reach the queue through
#: `load_manual`. DEF is absent from the board entirely (keeper_vorp.py's
#: EXCLUDE_POSITIONS) and K is excluded here -- see the module docstring.
MANUAL_POSITIONS = ("K", "DEF")

#: How many K and DEF to carry, per lens. The two lenses are unioned, so this
#: yields 8 kickers and 9 defenses rather than 10 of each.
MANUAL_PER_LENS = 5


def load_board(season: int, *, drafted_by_hand: bool = False) -> list[dict]:
    """The VORP board. Sorted here rather than trusted: keeper_vorp.py writes
    it in `vorp_avg` order today, but this file's whole contract is that order.

    `drafted_by_hand` keeps K and DEF in, for callers that want the raw board.
    """
    path = REPO_ROOT / "data" / f"vorp-snake-{season}.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = [
            row
            for row in csv.DictReader(f)
            if drafted_by_hand or row["position"] not in MANUAL_POSITIONS
        ]
    return sorted(rows, key=lambda r: -float(r["vorp_avg"]))


def team_byes(season: int) -> dict[str, str]:
    """`{team: bye_week}`, from whichever projection row happens to carry it.

    A bye is a property of the team, but the projections CSV only fills it in
    for players the hand-scraped board covers -- which is no kicker and only
    some defenses. Reading it off a team-mate resolves all 32.
    """
    byes: dict[str, str] = {}
    with projections_csv_path(season).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["team"] and row["bye_week"]:
                byes.setdefault(row["team"], row["bye_week"])
    return byes


def load_manual(season: int, per_lens: int = MANUAL_PER_LENS) -> list[dict]:
    """The K and DEF worth ranking: per position, the union of the top
    `per_lens` by ADP and the top `per_lens` by week-1 points.

    Two lenses because neither alone is right. ADP knows who is actually
    drafted but says nothing about week 1, and week 1 alone is close to noise
    at these positions -- the top thirty kickers span a single point -- so it
    promotes players nobody drafts. Spencer Shrader (ADP 468) and the Raiders
    defense (ADP 687) are in the set for exactly that reason; they lead the
    week-1 lens. The union keeps both readings visible and lets the
    comparisons decide.

    Rows come back in board shape, so every consumer downstream is unchanged.
    `vorp_avg` is empty for DEF, which the board genuinely does not carry.
    """
    byes = team_byes(season)
    # Kickers are on the board even though they are never queued from it, so
    # their vorp and season points come through. Defenses are not, and get
    # blanks -- an absent number, which the card renders as "--".
    on_board = {r["player_id"]: r for r in load_board(season, drafted_by_hand=True)}

    adp_path = REPO_ROOT / "data" / f"adp-{season}.csv"
    with adp_path.open(newline="", encoding="utf-8") as f:
        adp = {r["player_id"]: float(r["adp"]) for r in csv.DictReader(f) if r["adp"]}

    with projections_csv_path(season).open(newline="", encoding="utf-8") as f:
        rows = [
            {
                "player_id": r["player_id"],
                "player": r["player"],
                "position": r["position"],
                "team": r["team"],
                "bye": byes.get(r["team"], ""),
                "adp": str(adp[r["player_id"]]) if r["player_id"] in adp else "",
                "vorp_avg": on_board.get(r["player_id"], {}).get("vorp_avg", ""),
                "pts_sleeper": on_board.get(r["player_id"], {}).get("pts_sleeper", ""),
                "pts_boberto": on_board.get(r["player_id"], {}).get("pts_boberto", ""),
                "wk1": float(r["wk1_pts_league"]),
            }
            for r in csv.DictReader(f)
            if r["position"] in MANUAL_POSITIONS and r["wk1_pts_league"]
        ]

    picked: list[dict] = []
    for position in MANUAL_POSITIONS:
        pool = [r for r in rows if r["position"] == position]
        by_adp = sorted((r for r in pool if r["adp"]), key=lambda r: float(r["adp"]))
        by_week1 = sorted(pool, key=lambda r: -r["wk1"])
        keep = {r["player_id"] for r in by_adp[:per_lens]} | {
            r["player_id"] for r in by_week1[:per_lens]
        }
        picked += sorted(
            (r for r in pool if r["player_id"] in keep),
            # No ADP sorts last, the same convention load_pool uses for skill
            # players: unranked by the market means latest, not earliest.
            key=lambda r: float(r["adp"]) if r["adp"] else float("inf"),
        )
    return picked


def load_pool(season: int, size: int) -> list[dict]:
    """The players worth ranking by hand: the top `size` of the VORP board,
    plus the kickers and defenses `load_manual` selects.

    Lives here rather than in queue_builder because three callers need to agree
    on it exactly -- the builder page, the Bradley-Terry fit, and this module's
    own export. A pool that differed between them would silently drop answers:
    `fit_bradley_terry` discards a comparison naming a player it cannot see.
    """
    return load_board(season)[:size] + load_manual(season)


def load_ratings(season: int) -> dict[str, float]:
    """The queue ordering key from scripts/queue_builder.py, if it has run.
    Empty dict when the file is absent, which is the plain-VORP case.

    Reads `order`, not `ratings`: `order` is the round-blocked key the builder
    computed, and the raw Bradley-Terry `ratings` beside it must not be sorted
    on directly. See `queue_builder.queue_order` for why -- ordering by raw
    rating scored worse than using no preferences at all.
    """
    path = REPO_ROOT / "data" / f"queue-ratings-{season}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("order", {})


def order_board(board: list[dict], keys: dict[str, float]) -> list[dict]:
    """The queue order: the builder's key where it exists, VORP otherwise.

    Ascending -- the key is "effective round", so smaller comes first. `board`
    arrives in VORP order, so players sharing a key (anyone the preferences
    never reached) keep their board position, because the sort is stable.
    """
    if not keys:
        return board
    fallback = max(keys.values()) + 1 if keys else 0.0
    return sorted(board, key=lambda r: keys.get(r["player_id"], fallback))


def place_manual(ordered: list[dict], depth: int) -> list[dict]:
    """The queue: skill players first, then K and DEF at the back of it.

    K and DEF are ranked like everyone else, and then placed *after* every
    skill player the queue has room for. Their preference order still decides
    which kicker and which defense, and they are still queued -- autopick takes
    one once the skill players run out -- but they cannot displace a starter.

    Letting them sit at their rated position instead is what the ADP rounds
    give you, and it is measurably worse. 500 mocks against the current
    184-comparison fit, at every depth from 120 to 160:

        placement                  fieldable lineup    QB gap    TE gap
        rated position (74-117)          85%            10%        4%
        after the skill players          96%             4%        0%

    Deepening the queue does not help -- the numbers are identical at 140 and
    160 -- because the damage is done at the positions themselves: the mocks
    reach a median depth of ~107, so nine defenses and eight kickers sitting
    between 74 and 117 are inside the range autopick actually consumes, and
    each one is a pick not spent on the quarterback or tight end the roster
    still needs. This is the same failure the module docstring records from the
    VORP-ordered queue, just eighty slots later.
    """
    manual = [r for r in ordered if r["position"] in MANUAL_POSITIONS]
    skill = [r for r in ordered if r["position"] not in MANUAL_POSITIONS]
    return skill[: max(0, depth - len(manual))] + manual


def load_my_keepers(season: int) -> list[dict]:
    path = REPO_ROOT / "data" / f"snake-draft-{season}-picks.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return [
            row
            for row in csv.DictReader(f)
            if row["is_keeper"] == "True" and row["owner"] == MY_USERNAME
        ]


def surname(player: str) -> str:
    """What I actually type into Sleeper's search box."""
    return player.split(" ", 1)[1] if " " in player else player


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    season = int(args[0]) if args else SNAKE_CONFIG.season
    depth = int(sys.argv[sys.argv.index("--depth") + 1] if "--depth" in sys.argv else DEFAULT_DEPTH)

    keepers = load_my_keepers(season)
    ratings = load_ratings(season)
    # The whole board, so unrated players still fill the tail, plus the K and
    # DEF the builder ranks. Without ratings those trail every skill player and
    # fall past `depth` -- which is the old hand-draft behaviour, and the right
    # default: nothing has been said about them yet to justify queueing one.
    queue = place_manual(order_board(load_board(season) + load_manual(season), ratings), depth)
    picks = SNAKE_CONFIG.roster_size - len(keepers)
    source = f"pairwise preferences over {len(ratings)} players" if ratings else "pure VORP"

    out_path = REPO_ROOT / "data" / f"queue-snake-{season}.csv"
    fields = ["queue_pos", "player_id", "player", "position", "team", "bye", "adp", "vorp_avg"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for i, row in enumerate(queue, 1):
            writer.writerow({"queue_pos": i, **row})

    kept = ", ".join(f"{k['player_name']} ({k['position']})" for k in keepers)
    print(f"Keeping {kept} -- {picks} live picks, queue {len(queue)} deep ({source})\n")
    print("Enter top-down; Sleeper's queue appends to the bottom, so no dragging.\n")
    for i, row in enumerate(queue, 1):
        adp = f"{float(row['adp']):>6.1f}" if row["adp"] else "    --"
        # DEF has no vorp -- it is off the board entirely, which is not a zero.
        vorp = f"{float(row['vorp_avg']):>6.1f}" if row["vorp_avg"] else "    --"
        print(
            f"  {i:>3}. {surname(row['player']):<18} {row['position']:<4} {row['team']:<4} "
            f"bye {row['bye']:<3} adp {adp}  vorp {vorp}"
        )

    tally = Counter(r["position"] for r in queue)
    print("\nQueue shape:  " + "  ".join(f"{p} {n}" for p, n in tally.most_common()))
    print(f"First {picks}:     " + "  ".join(
        f"{p} {n}" for p, n in Counter(r["position"] for r in queue[:picks]).most_common()
    ))
    print(f"\nWrote {out_path.relative_to(REPO_ROOT)}")


def demo() -> None:
    """Without ratings the queue is the board in board order; with them it is
    the ratings' order, and players the preferences never reached keep their
    board position among themselves.
    """
    board = load_board(SNAKE_CONFIG.season)
    queue = order_board(board, {})[:DEFAULT_DEPTH]
    vorps = [float(r["vorp_avg"]) for r in queue]

    assert len(queue) == DEFAULT_DEPTH, f"queue only {len(queue)} deep"
    assert vorps == sorted(vorps, reverse=True), "queue is not in VORP order"
    assert [r["player"] for r in queue] == [r["player"] for r in board[:DEFAULT_DEPTH]]

    # Keys sort ascending. Give the board's 50th player the earliest key and
    # its first a later one; both must land ahead of everyone unkeyed, since
    # the builder only ranks the top of the board and the rest is still VORP.
    promoted, demoted = board[49]["player_id"], board[0]["player_id"]
    keyed = {promoted: 0.0, demoted: 99.0}
    ranked = order_board(board, keyed)
    assert ranked[0]["player_id"] == promoted, "key did not promote"
    assert ranked[1]["player_id"] == demoted, "key did not order the keyed pair"
    unrated = [r["player"] for r in ranked[2:]]
    assert unrated == [r["player"] for r in board if r["player_id"] not in keyed], (
        "unrated players lost board order"
    )

    # The manual set: both lenses represented, board shape honoured, and a bye
    # on every row -- the whole point of team_byes, since no kicker carries one
    # of his own.
    manual = load_manual(SNAKE_CONFIG.season)
    kickers = [r for r in manual if r["position"] == "K"]
    defenses = [r for r in manual if r["position"] == "DEF"]
    assert kickers and defenses, "manual set must carry both positions"
    assert all(r["bye"] for r in manual), "a K or DEF came through with no bye week"
    written = {"player_id", "player", "position", "team", "bye", "adp", "vorp_avg"}
    assert all(written <= set(r) for r in manual), (
        "a manual row is missing a column the queue CSV writes"
    )
    assert all(r["vorp_avg"] == "" for r in defenses), "DEF is off the board, so it has no vorp"

    # The week-1 lens must actually reach past the ADP lens, or the union is
    # doing nothing: the set has to be larger than one lens alone.
    assert len(kickers) > MANUAL_PER_LENS, "union no wider than the ADP top 5"
    assert max(r["wk1"] for r in kickers) > max(
        r["wk1"] for r in sorted(kickers, key=lambda r: float(r["adp"] or "inf"))[:MANUAL_PER_LENS]
    ), "the week-1 lens added nobody the ADP lens missed"

    # K and DEF are queued, but only behind every skill player that fits. See
    # `place_manual` for the 85%-vs-96% measurement behind that.
    placed = place_manual(order_board(load_board(SNAKE_CONFIG.season) + manual, {}), DEFAULT_DEPTH)
    assert len(placed) == DEFAULT_DEPTH, f"placed queue is {len(placed)} deep"
    assert all(r["position"] in MANUAL_POSITIONS for r in placed[-len(manual):]), (
        "K/DEF are not at the back of the queue"
    )
    assert not any(r["position"] in MANUAL_POSITIONS for r in placed[: -len(manual)]), (
        "a K or DEF landed among the skill players"
    )
    assert {r["player_id"] for r in manual} == {r["player_id"] for r in placed[-len(manual):]}, (
        "placing dropped or duplicated a manual player"
    )

    pool = load_pool(SNAKE_CONFIG.season, 100)
    assert len(pool) == 100 + len(manual), f"pool is {len(pool)}, expected 100 + {len(manual)}"
    assert len({r["player_id"] for r in pool}) == len(pool), "pool has a duplicate"
    assert not any(r["position"] in MANUAL_POSITIONS for r in pool[:100]), (
        "a K or DEF leaked into the skill half of the pool"
    )
    print(f"ok: {len(queue)} queued, VORP order by default, ratings reorder when present; "
          f"pool {len(pool)} = 100 skill + {len(kickers)} K + {len(defenses)} DEF")


if __name__ == "__main__":
    demo() if "--check" in sys.argv else main()
