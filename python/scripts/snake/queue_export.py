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

Depth is the whole draft: `draft_slots` -- 10 teams x 16 rounds less the 18
keepers, 142 live picks. Mocks stop improving around 90, but a queue that ends
before the draft does hands the tail back to Sleeper's board, which still has
every keeper on it, so there is nothing to be gained by stopping short.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from keeper_vorp import load_keepers, pick_schedule  # noqa: E402
from vorp.csv_loader import REPO_ROOT, projections_csv_path  # noqa: E402
from vorp.league.config import MY_USERNAME, SNAKE_CONFIG  # noqa: E402

#: Not on the VORP board, so they only reach the queue through
#: `load_manual`. DEF is absent from the board entirely (keeper_vorp.py's
#: EXCLUDE_POSITIONS) and K is excluded here -- see the module docstring.
MANUAL_POSITIONS = ("K", "DEF")

#: How many K and DEF to carry, per lens. The two lenses are unioned, so this
#: yields 8 kickers and 9 defenses rather than 10 of each.
MANUAL_PER_LENS = 5


#: The earliest round I will take a given quarterback. VORP rates the position
#: higher than I do -- it had Maye at row 33 and four more QBs inside row 60 --
#: and no ordering rule fixes that, because the disagreement is with the number
#: itself, not with the sort. So the rounds are stated outright.
#:
#: Rounds, not ranks, because that is how the decision is made at the table:
#: "not before the 7th" is a thing I can hold in my head; "not before row 53"
#: is not. `round_start` does the translation.
QB_FLOOR = {"Drake Maye": 5, "Jalen Hurts": 7, "Joe Burrow": 7, "Jayden Daniels": 7}

#: Quarterbacks worth their board rank -- no floor at all. One name today.
QB_FREE = ("Josh Allen",)

#: Everyone unnamed above. Late enough that autopick will never reach a second
#: quarterback before the roster is otherwise full.
QB_DEFAULT_ROUND = 12


def draft_slots(season: int) -> int:
    """Picks actually up for grabs: every seat in the draft, less the keepers.

    10 teams x 16 rounds = 160, minus the 18 keepers already on rosters = 142
    live picks. That is how deep the queue has to go to cover the whole draft,
    and how many players are worth ranking in the builder.
    """
    path = REPO_ROOT / "data" / "snake" / f"snake-draft-{season}-picks.csv"
    with path.open(newline="", encoding="utf-8") as f:
        keepers = sum(row["is_keeper"] == "True" for row in csv.DictReader(f))
    return SNAKE_CONFIG.teams * SNAKE_CONFIG.roster_size - keepers


def load_board(season: int, *, drafted_by_hand: bool = False) -> list[dict]:
    """The VORP board. Sorted here rather than trusted: keeper_vorp.py writes
    it in `vorp_avg` order today, but this file's whole contract is that order.

    `drafted_by_hand` keeps K and DEF in, for callers that want the raw board.
    """
    path = REPO_ROOT / "data" / "snake" / f"vorp-snake-{season}.csv"
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


def round_start(season: int) -> dict[int, int]:
    """`{round: first row of that round}` in *live* rows -- keeper picks skipped.

    The queue and the live-ranking page are both one flat list whose Nth row is
    roughly the Nth live pick, so a round is a row range in it. Keepers make
    that range narrower than teams-per-round: round 5 starts at row 38, not 41.
    """
    keepers = load_keepers(season)
    starts: dict[int, int] = {}
    for pick in pick_schedule(keepers, 1, SNAKE_CONFIG):
        if pick["live_no"] is not None:
            starts.setdefault(pick["round"], pick["live_no"])
    return starts


def _name_pos(row: dict) -> tuple[str, str]:
    """Board rows carry `player`/`position`, payload entries `name`/`pos`. Both
    orderings need the floor, and neither shape is worth converting for it."""
    return row.get("player") or row["name"], row.get("position") or row["pos"]


def apply_qb_floor(rows: list[dict], season: int) -> list[dict]:
    """`rows`, with every quarterback moved down to the first row of the
    earliest round I'd take him in -- see QB_FLOOR.

    Placement, not a sort key. Sinking several QBs out of the same stretch of
    the board frees the rows above them, and a key-based sort lets the last one
    drift back up into those rows: three round-7 QBs came out at rows 51, 52
    and 53. Reinserting them into the list they left is exact.

    Only ever sinks. A QB already past his floor, and everyone who is not a
    quarterback, keeps the position the board gave him.
    """
    starts = round_start(season)
    rest, sinking = [], {}
    for i, row in enumerate(rows):
        name, pos = _name_pos(row)
        floor = starts.get(QB_FLOOR.get(name, QB_DEFAULT_ROUND), 1)
        if pos == "QB" and name not in QB_FREE and i + 1 < floor:
            sinking.setdefault(floor, []).append(row)
        else:
            rest.append(row)

    # Ascending, so a group inserted earlier is already in place when the next
    # floor is counted off -- which is what keeps every group at or below its
    # own row rather than sitting on top of the group beneath it.
    for floor in sorted(sinking):
        rest[floor - 1 : floor - 1] = sinking[floor]

    names = {_name_pos(row)[0] for row in rows}
    missing = [n for n in (*QB_FLOOR, *QB_FREE) if n not in names]
    if missing:
        print(f"WARNING: QB floor names not on the board: {missing}")
    return rest


def prefs_path(season: int) -> Path:
    """The builder's answers file.

    Lives here rather than in queue_builder because this module is the one the
    queue CSV comes out of, and queue_builder already imports from it.
    """
    return REPO_ROOT / "data" / "snake" / f"queue-prefs-{season}.json"


def load_prefs(season: int) -> dict:
    """The builder's answers, or {} when it has never run.

    Carries more than answers now. `extras` are board-tail players pulled into
    the ranked pool by hand, `rounds` are per-player round overrides, and
    `excluded` is the do-not-draft list. They ride in this file rather than one
    of their own because it is the only thing that syncs both ways: the phone
    POSTs it to queue_server, which writes the whole body through, so a player
    removed on a phone reaches this export with no extra plumbing.
    """
    path = prefs_path(season)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def queue_rows(season: int, prefs: dict) -> list[dict]:
    """Everything eligible for the queue: the whole board plus the K and DEF,
    less the do-not-draft list.

    Filtered here, before ordering and before `place_manual`, so the queue
    stays `depth` deep -- dropping a player pulls the next one up behind him
    rather than leaving a hole in the middle of the draft. Every consumer
    (draft_watch, draft_auto, mock_draft) reads only the exported CSV, so this
    one filter is what makes "do not draft" mean it.
    """
    excluded = set(prefs.get("excluded", ()))
    return [
        r
        for r in load_board(season) + load_manual(season)
        if r["player_id"] not in excluded
    ]


def load_ratings(season: int) -> dict[str, float]:
    """The queue ordering key from scripts/queue_builder.py, if it has run.
    Empty dict when the file is absent, which is the plain-VORP case.

    Reads `order`, not `ratings`: `order` is the round-blocked key the builder
    computed, and the raw Bradley-Terry `ratings` beside it must not be sorted
    on directly. See `queue_builder.queue_order` for why -- ordering by raw
    rating scored worse than using no preferences at all.
    """
    path = REPO_ROOT / "data" / "snake" / f"queue-ratings-{season}.json"
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
    path = REPO_ROOT / "data" / "snake" / f"snake-draft-{season}-picks.csv"
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
    depth = int(sys.argv[sys.argv.index("--depth") + 1] if "--depth" in sys.argv else draft_slots(season))

    keepers = load_my_keepers(season)
    ratings = load_ratings(season)
    prefs = load_prefs(season)
    # The whole board, so unrated players still fill the tail, plus the K and
    # DEF the builder ranks. Without ratings those trail every skill player and
    # fall past `depth` -- which is the old hand-draft behaviour, and the right
    # default: nothing has been said about them yet to justify queueing one.
    # Floor last: `place_manual` pulls every skill player up by the K and DEF
    # it moves to the back, which would land a floored QB eight rows above his
    # round. The rows the floor counts have to be the rows that ship.
    queue = apply_qb_floor(place_manual(order_board(queue_rows(season, prefs), ratings), depth), season)
    picks = SNAKE_CONFIG.roster_size - len(keepers)
    source = f"pairwise preferences over {len(ratings)} players" if ratings else "pure VORP"

    out_path = REPO_ROOT / "data" / "snake" / f"queue-snake-{season}.csv"
    fields = ["queue_pos", "player_id", "player", "position", "team", "bye", "adp", "vorp_avg"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for i, row in enumerate(queue, 1):
            writer.writerow({"queue_pos": i, **row})

    kept = ", ".join(f"{k['player_name']} ({k['position']})" for k in keepers)
    print(f"Keeping {kept} -- {picks} live picks, queue {len(queue)} deep ({source})\n")
    if prefs.get("excluded"):
        # Said out loud, because a player missing from the queue is otherwise
        # indistinguishable from one the depth cut off.
        names = {r["player_id"]: r["player"] for r in load_board(season) + load_manual(season)}
        dnd = ", ".join(names.get(i, i) for i in prefs["excluded"])
        print(f"Do not draft ({len(prefs['excluded'])}): {dnd}\n")
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
    depth = draft_slots(SNAKE_CONFIG.season)
    queue = order_board(board, {})[:depth]
    vorps = [float(r["vorp_avg"]) for r in queue]

    assert len(queue) == depth, f"queue only {len(queue)} deep"
    assert vorps == sorted(vorps, reverse=True), "queue is not in VORP order"
    assert [r["player"] for r in queue] == [r["player"] for r in board[:depth]]

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
    placed = place_manual(order_board(load_board(SNAKE_CONFIG.season) + manual, {}), depth)
    assert len(placed) == depth, f"placed queue is {len(placed)} deep"
    assert all(r["position"] in MANUAL_POSITIONS for r in placed[-len(manual):]), (
        "K/DEF are not at the back of the queue"
    )
    assert not any(r["position"] in MANUAL_POSITIONS for r in placed[: -len(manual)]), (
        "a K or DEF landed among the skill players"
    )
    assert {r["player_id"] for r in manual} == {r["player_id"] for r in placed[-len(manual):]}, (
        "placing dropped or duplicated a manual player"
    )

    # Do not draft: filtered before ordering, so the queue is still full depth
    # -- the next player up fills the hole rather than the queue ending a pick
    # short of the draft.
    banned = board[0]["player_id"]
    rows = queue_rows(SNAKE_CONFIG.season, {"excluded": [banned]})
    assert banned not in {r["player_id"] for r in rows}, "excluded player survived"
    assert len(rows) == len(board) + len(manual) - 1, "exclusion dropped more than one"
    assert len(place_manual(order_board(rows, {}), depth)) == depth, "queue lost depth"
    assert queue_rows(SNAKE_CONFIG.season, {}) == board + manual, "no prefs must be a no-op"

    # QB floor: sinks the named quarterbacks to their round, holds Josh Allen
    # where the board has him, and never promotes anyone.
    season = SNAKE_CONFIG.season
    starts = round_start(season)
    before = [r["player"] for r in board]
    after = [r["player"] for r in apply_qb_floor(board, season)]
    assert after.index("Josh Allen") == before.index("Josh Allen"), "QB_FREE was moved"
    assert after.index("Drake Maye") >= starts[QB_FLOOR["Drake Maye"]] - 1, "Maye above his round"
    assert all(after.index(q) >= starts[7] - 1 for q in ("Jalen Hurts", "Joe Burrow", "Jayden Daniels"))
    floored = starts[QB_DEFAULT_ROUND] - 1
    assert all(
        after.index(r["player"]) >= floored
        for r in board
        if r["position"] == "QB" and r["player"] not in QB_FLOOR and r["player"] not in QB_FREE
    ), "an unnamed QB sits above the default floor"
    # Only ever sinks: a QB already past his floor keeps his place, and no
    # non-QB is reordered relative to another non-QB.
    deep = next(r["player"] for r in reversed(board) if r["position"] == "QB")
    assert after.index(deep) == before.index(deep), "a deep QB was promoted"
    skill = [n for n in after if n not in {r["player"] for r in board if r["position"] == "QB"}]
    assert skill == [n for n in before if n in set(skill)], "the floor reordered non-QBs"

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
