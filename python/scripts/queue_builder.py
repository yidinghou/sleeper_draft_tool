#!/usr/bin/env python3
"""Build the draft queue from pairwise preferences instead of from VORP.

Two commands:

  (no args)  writes data/queue-builder-{season}.html -- a local page that asks
             "which of these two would you rather have?" and records answers.
  --fit      reads the answers the page exports and writes
             data/queue-ratings-{season}.json, which queue_export.py then uses
             as the queue order in place of vorp_avg.

Why Bradley-Terry and not a sort. Sorting 90 players by asking comparisons
takes ~550 questions and, worse, is brittle: a comparison sort trusts every
answer absolutely, so one misclick silently corrupts the order and there is no
way to detect or repair it. Bradley-Terry instead fits a strength to each
player from *all* the answers at once, so a contradictory answer is outvoted
rather than obeyed, and a partial run still produces a usable ranking -- it
just has wider error bars. You can stop whenever the top of the board stops
moving.

No VORP prior. Every rating starts equal and only the answers move it, so the
result is genuinely the preferences and not a nudged version of the board. VORP
is still used for one thing: deciding which pairs are worth *asking about*
early, before there are enough answers for the model to choose for itself. That
affects which questions you see, never what the answers are worth.

The model. Each player has a strength pi_i > 0, and

    P(i preferred over j) = pi_i / (pi_i + pi_j)

fit by Hunter's MM algorithm, which is the standard iteration for this and
needs no gradient step size. Ratings are reported as log(pi).

Usage: python scripts/queue_builder.py [season] [--pool N]
       python scripts/queue_builder.py [season] --fit [--prefs PATH]
       python scripts/queue_builder.py --check
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from html_page import write_local  # noqa: E402
from queue_export import load_pool  # noqa: E402
from vorp.csv_loader import REPO_ROOT, projections_csv_path  # noqa: E402
from vorp.league.config import SNAKE_CONFIG  # noqa: E402

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "queue_builder.html"

#: Skill players to rank. K and DEF are added on top of this by `load_pool`,
#: so the pool is larger than this number -- 117 today.
DEFAULT_POOL = 100

#: Pseudo-comparisons against an average opponent, added to every player.
#: Without it the MM iteration diverges for anyone who has won every comparison
#: (strength runs to infinity) or lost every one (to zero), which is the state
#: most players are in early in a run. It also shrinks a player seen twice
#: toward the middle, so a lucky single win doesn't outrank a long record.
#:
#: Kept low because the question schedule is *local*: pairs come from within a
#: round or across adjacent rounds, so a player's evidence never touches most
#: of the pool and the long-range order has to survive a chain of overlaps. A
#: shared anchor fights that chain. Measured on 40 players in tiers of 5, the
#: recovered global order against a known truth was
#:
#:     reg  0.10   0.25   0.50   1.00   2.00
#:     rho  0.997  0.993  0.971  0.886  0.744
#:
#: and at 1.0 the tier medians were no longer even monotonic -- rounds would
#: scramble in the finished queue. 0.25 keeps the chain intact while still
#: shrinking a one-comparison player; going lower buys ~0.004 of rho and gives
#: that shrinkage up. Randomly-paired comparisons are insensitive to this
#: (rho 0.911-0.914 across the whole range), which is why it only showed up
#: once the questions became round-aware.
REGULARIZATION = 0.25

#: MM stops when no strength moves by more than this in log space.
TOLERANCE = 1e-9
MAX_ITERATIONS = 10_000


def fit_bradley_terry(
    player_ids: list[str], comparisons: list[dict], reg: float = REGULARIZATION
) -> dict[str, float]:
    """Strengths from pairwise answers, by Hunter's MM iteration.

    `comparisons` are {"winner": id, "loser": id}. Returns id -> log strength,
    centred on zero. Players with no comparisons come back at 0.0.
    """
    index = {pid: i for i, pid in enumerate(player_ids)}
    n = len(player_ids)
    wins = [0.0] * n
    # pair_counts[(i, j)] with i < j: how many times the two were compared.
    pair_counts: dict[tuple[int, int], int] = {}

    for c in comparisons:
        w, l = c.get("winner"), c.get("loser")
        if w not in index or l not in index or w == l:
            continue  # a player dropped from the pool since the answer
        i, j = index[w], index[l]
        wins[i] += 1
        key = (i, j) if i < j else (j, i)
        pair_counts[key] = pair_counts.get(key, 0) + 1

    # opponents[i] = list of (j, n_ij)
    opponents: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    for (i, j), count in pair_counts.items():
        opponents[i].append((j, count))
        opponents[j].append((i, count))

    strength = [1.0] * n
    for _ in range(MAX_ITERATIONS):
        updated = []
        for i in range(n):
            # Regularisation acts as `reg` wins and `reg` losses against an
            # anchor of strength 1, which is why it appears on both sides.
            denominator = 2.0 * reg / (strength[i] + 1.0)
            for j, count in opponents[i]:
                denominator += count / (strength[i] + strength[j])
            updated.append((wins[i] + reg) / denominator if denominator else 1.0)

        # Normalise to geometric mean 1 so the scale can't drift between passes.
        log_mean = sum(math.log(s) for s in updated) / n
        updated = [s / math.exp(log_mean) for s in updated]

        shift = max(abs(math.log(a) - math.log(b)) for a, b in zip(updated, strength))
        strength = updated
        if shift < TOLERANCE:
            break

    return {pid: math.log(strength[index[pid]]) for pid in player_ids}


def adp_round(adp: float | None, teams: int, fallback: int, last: int | None = None) -> int:
    """Which round a player comes off the board in, from ADP.

    This is the grouping the questions are built on: two players in the same
    round are two players I could actually be choosing between at one turn.
    Board rank would be the wrong grouping -- Derrick Henry is 7th on the board
    but goes at ADP 16.4, so he is a round-2 decision, and pairing him against
    Gibbs would ask about a choice I will never get.

    `last` caps the answer at the final round of the draft. Kickers and
    defenses arrive with ADPs far past the end of it -- Spencer Shrader at 468
    computes to round 47 against a 16-round draft, the Raiders defense to 69 --
    and an uncapped round puts each of them alone in a round of his own. The
    scheduler cannot draw a within-round pair from a single player, so those
    rounds would fall through to its widening fallback and `round_target` would
    be budgeting for rounds that do not exist.
    """
    if adp is None:
        return fallback if last is None else min(fallback, last)
    rnd = max(1, math.ceil(adp / teams))
    return rnd if last is None else min(rnd, last)


def round_target(rnd: int) -> int:
    """Comparisons to spend per player in a round.

    Front-loaded on purpose. VORP falls ~9.5 points per board slot across the
    first ten players and ~0.7 by rank 60, so evidence buys roughly fourteen
    times as much at the top -- and a wrong answer there costs a first-rounder
    rather than a bench body. Rounds 1-2 get four times the evidence per player
    that round 10 does.
    """
    return max(2, min(8, 9 - rnd))


def components(player_ids: list[str], comparisons: list[dict]) -> list[list[str]]:
    """Connected components of the comparison graph, largest first.

    Bradley-Terry can only rank two players against each other if some chain of
    comparisons joins them. Across a split, the fitted numbers are held together
    by REGULARIZATION alone -- they look comparable and are not. The overlapping
    round schedule is meant to keep this at one component; this reports whether
    it actually did.
    """
    parent = {pid: pid for pid in player_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c in comparisons:
        a, b = c.get("winner"), c.get("loser")
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

    groups: dict[str, list[str]] = {}
    for pid in player_ids:
        groups.setdefault(find(pid), []).append(pid)
    return sorted(groups.values(), key=len, reverse=True)


#: How far, in rounds, a player may drift from his ADP round on the strength of
#: his comparisons. 1.0 lets a convincing round-2 player finish inside round 1.
ROUND_SLACK = 1.0

#: Comparisons at which a player's drift counts for full. Below it he moves
#: proportionally less, so a 2-comparison record can't relocate anyone.
CONFIDENCE_AT = 6


def queue_order(
    rounds: dict[str, int],
    ratings: dict[str, float],
    counts: dict[str, int],
    slack: float = ROUND_SLACK,
) -> dict[str, float]:
    """The final queue key: lower sorts earlier.

    ADP round is the backbone and preferences order players *within* a round,
    with a bounded drift across rounds for anyone whose record earns it.

    Sorting by raw Bradley-Terry rating instead is what the obvious
    implementation does, and it is badly wrong here. The questions are local by
    design -- within a round or across one boundary -- so the only thing tying
    round 1 to round 12 is a twelve-link chain carrying two to eight
    comparisons per player. That is far too thin, and thinly-compared tail
    players float to the top: measured against a known set of preferences on
    200 answers, ordering by raw rating scored rho 0.404 and put five players
    from board rank 40+ in the top ten, which is *worse than asking no
    questions at all* (board order alone scores 0.787). Round-blocking the same
    ratings scores 0.847 with no such promotions.

    Within a round the ratings are dense and trustworthy, which is why they are
    used there and only nudge across the boundary.
    """
    by_round: dict[int, list[float]] = {}
    for pid, rnd in rounds.items():
        by_round.setdefault(rnd, []).append(ratings.get(pid, 0.0))

    centre = {r: statistics.median(v) for r, v in by_round.items()}
    spread = {r: (statistics.pstdev(v) if len(v) > 1 else 0.0) or 1.0 for r, v in by_round.items()}

    key = {}
    for pid, rnd in rounds.items():
        z = (ratings.get(pid, 0.0) - centre[rnd]) / spread[rnd]
        drift = max(-slack, min(slack, -z * slack / 2))
        confidence = min(1.0, counts.get(pid, 0) / CONFIDENCE_AT)
        key[pid] = rnd + drift * confidence
    return key


def comparison_counts(player_ids: list[str], comparisons: list[dict]) -> dict[str, int]:
    counts = {pid: 0 for pid in player_ids}
    for c in comparisons:
        for side in ("winner", "loser"):
            if c.get(side) in counts:
                counts[c[side]] += 1
    return counts


def prefs_path(season: int) -> Path:
    return REPO_ROOT / "data" / f"queue-prefs-{season}.json"


def ratings_path(season: int) -> Path:
    return REPO_ROOT / "data" / f"queue-ratings-{season}.json"


def load_week1(season: int) -> dict[str, float]:
    """Week-1 projected points by player_id, from the projections CSV.

    The board CSV carries season points only, so this is the one thing the
    builder reads outside it. Missing players are simply absent -- the card
    shows "--" rather than a zero, which would read as "projected to score
    nothing" instead of "unknown".
    """
    with projections_csv_path(season).open(newline="", encoding="utf-8") as f:
        return {
            row["player_id"]: float(row["wk1_pts_league"])
            for row in csv.DictReader(f)
            if row.get("wk1_pts_league")
        }


def season_points(player: dict) -> float | None:
    """The blended season projection: Sleeper and Boberto averaged over
    whichever of the two actually has a number. None when neither does, which
    is every defense -- no projection is not the same claim as zero points.
    """
    sources = [float(player[k]) for k in ("pts_sleeper", "pts_boberto") if player.get(k)]
    return round(sum(sources) / len(sources), 1) if sources else None


def payload_path(season: int) -> Path:
    return REPO_ROOT / "data" / f"queue-payload-{season}.json"


def build_payload(season: int, pool_size: int = 100) -> dict:
    """Everything the page needs, with no answers in it.

    Split out from `build_page` and written to disk because the Railway server
    cannot rebuild it: `data/vorp-snake-{season}.csv` and `data/adp-{season}.csv`
    are gitignored, so a deploy has no board to read. This one file is
    committed instead of shipping the whole VORP pipeline to a web dyno.
    """
    players = load_pool(season, pool_size)
    week1 = load_week1(season)
    teams, last = SNAKE_CONFIG.teams, SNAKE_CONFIG.roster_size

    entries = [
        {
            "id": p["player_id"],
            "name": p["player"],
            "pos": p["position"],
            "team": p["team"],
            "bye": p["bye"],
            "adp": float(p["adp"]) if p["adp"] else None,
            # DEF is off the VORP board entirely, so this is genuinely absent
            # rather than zero, and the card renders it as "--".
            "vorp": float(p["vorp_avg"]) if p["vorp_avg"] else None,
            # No ADP means the market never ranked him: last round, not first,
            # which is where `ceil(None / teams)` would land him.
            "rnd": adp_round(float(p["adp"]) if p["adp"] else None, teams, last, last=last),
            # Averaged over whichever projections exist; None when neither
            # does, which is every defense.
            "pts": season_points(p),
            "wk1": round(week1[p["player_id"]], 1) if p["player_id"] in week1 else None,
        }
        for p in players
    ]
    rounds = sorted({e["rnd"] for e in entries})
    return {
        "season": season,
        # The *skill* pool size, which is what `load_pool` takes -- not
        # len(entries), which counts the K and DEF it appends. The page echoes
        # this back in its export so `--fit` rebuilds the identical pool.
        "pool": pool_size,
        "players": entries,
        "rounds": rounds,
        "targets": {str(r): round_target(r) for r in rounds},
    }


def render(payload: dict) -> str:
    """The page fragment, with the payload inlined."""
    return (
        TEMPLATE_PATH.read_text(encoding="utf-8")
        .replace("__DATA__", json.dumps(payload, separators=(",", ":")))
        .replace("__SEASON__", str(payload["season"]))
    )


def build_page(season: int, pool_size: int) -> None:
    payload = build_payload(season, pool_size)
    entries, rounds = payload["players"], payload["rounds"]
    players = entries

    payload_path(season).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    existing = prefs_path(season)
    if existing.exists():
        payload = {**payload, "resume": json.loads(existing.read_text(encoding="utf-8"))}

    budget = sum(round_target(e["rnd"]) for e in entries) // 2

    write_local(render(payload), REPO_ROOT / "data", f"queue-builder-{season}")
    out = REPO_ROOT / "data" / f"queue-builder-{season}.html"
    print(f"Wrote {out.relative_to(REPO_ROOT)}  ({len(players)} players to rank)")
    counts = Counter(e["rnd"] for e in entries)
    print(f"\n  {'ROUND':<7}{'PLAYERS':>8}{'PER PLAYER':>12}{'PAIRS':>7}")
    for r in rounds:
        print(f"  {r:<7}{counts[r]:>8}{round_target(r):>12}{counts[r] * round_target(r) // 2:>7}")
    print(f"  {'total':<7}{len(entries):>8}{'':>12}{budget:>7}")
    no_wk1 = [e["name"] for e in entries if e["wk1"] is None]
    if no_wk1:
        print(f"\n  {len(no_wk1)} of {len(entries)} have no week-1 projection "
              f"(shown as --): {', '.join(no_wk1[:5])}")
    print(f"\n  open {out.relative_to(REPO_ROOT)}")
    print(f"\nAnswer pairs, hit Export, and save it as {prefs_path(season).relative_to(REPO_ROOT)}. Then:")
    print(f"\n  python3 python/scripts/queue_builder.py {season} --fit")
    print("  python3 python/scripts/queue_export.py")


def fit_and_write(season: int, path: Path) -> None:
    if not path.exists():
        sys.exit(f"No answers at {path}. Export them from the builder page first.")
    saved = json.loads(path.read_text(encoding="utf-8"))
    comparisons = saved.get("comparisons", saved if isinstance(saved, list) else [])
    # Built the same way the page is, so the fit sees exactly the pool that was
    # on screen. Re-deriving the rounds here instead would let the two drift
    # apart, and `fit_bradley_terry` silently drops any comparison naming a
    # player its pool does not contain.
    #
    # The current pool wins over the one the answers were given against, when
    # it is larger. Growing the pool keeps every old answer valid -- the old
    # players are all still in it -- and the extra players need ratings to be
    # queued at all. Shrinking it is the case that would drop answers, so the
    # answers' own pool sets the floor.
    on_disk = json.loads(payload_path(season).read_text()).get("pool", 0) if payload_path(season).exists() else 0
    payload = build_payload(season, max(saved.get("pool", DEFAULT_POOL), on_disk))
    players = payload["players"]
    by_id = {p["id"]: p for p in players}
    ids = [p["id"] for p in players]
    rounds = {p["id"]: p["rnd"] for p in players}

    ratings = fit_bradley_terry(ids, comparisons)
    counts = comparison_counts(ids, comparisons)
    keys = queue_order(rounds, ratings, counts)
    order = sorted(ids, key=lambda pid: keys[pid])

    ratings_path(season).write_text(
        json.dumps(
            {
                "season": season,
                "comparisons": len(comparisons),
                # `order` is what the queue sorts by, ascending. `ratings` is
                # the raw Bradley-Terry strength kept for inspection -- do not
                # sort by it, see `queue_order`.
                "order": {pid: round(keys[pid], 6) for pid in ids},
                "ratings": {pid: round(ratings[pid], 6) for pid in ids},
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    unseen = [pid for pid in ids if counts[pid] == 0]
    print(f"{len(comparisons)} comparisons over {len(ids)} players "
          f"({len(ids) - len(unseen)} seen, {len(unseen)} never shown)\n")

    # Ratings are only comparable within a connected component -- see
    # `components`. Report a split loudly, because the output looks fine.
    groups = [g for g in components(ids, comparisons) if len(g) > 1 or counts[g[0]]]
    if len(groups) > 1:
        print(f"WARNING: the comparisons split into {len(groups)} disconnected groups.")
        print("Ratings are only meaningful *within* a group; across them they are held")
        print("together by the regularisation term, not by anything you answered.")
        for g in groups[:4]:
            names = ", ".join(by_id[p]["name"] for p in g[:4])
            print(f"  {len(g):>3} players: {names}{' ...' if len(g) > 4 else ''}")
        print("Answer a few pairs spanning them to join the groups up.\n")
    print(f"  {'#':>3}  {'PLAYER':<24}{'POS':<5}{'RD':>4}{'RATING':>8}{'SEEN':>6}   {'BOARD':>6}")
    vorp_rank = {pid: i + 1 for i, pid in enumerate(ids)}  # pool is VORP-sorted
    for i, pid in enumerate(order[:20], 1):
        p = by_id[pid]
        move = vorp_rank[pid] - i
        arrow = f"{vorp_rank[pid]:>6}" + (f"  {move:+d}" if move else "")
        print(f"  {i:>3}  {p['name']:<24}{p['pos']:<5}{rounds[pid]:>4}"
              f"{ratings[pid]:>8.2f}{counts[pid]:>6}   {arrow}")
    drifted = sorted(ids, key=lambda pid: keys[pid] - rounds[pid])[:3]
    moved = [pid for pid in drifted if keys[pid] - rounds[pid] < -0.25]
    if moved:
        print("\nBiggest cross-round promotions (your answers beating the ADP round):")
        for pid in moved:
            print(f"  {by_id[pid]['name']:<24} round {rounds[pid]} "
                  f"-> {keys[pid]:.2f}  ({counts[pid]} comparisons)")
    if unseen:
        print(f"\n{len(unseen)} players never compared -- they hold their ADP round and sort "
              f"by the board within it. Answer more pairs to place them.")
    print(f"\nWrote {ratings_path(season).relative_to(REPO_ROOT)}")
    print("queue_export.py will now use this order. Run it to rewrite the queue CSV.")


def demo() -> None:
    """Recover a known ranking from noisy comparisons.

    The point of Bradley-Terry over a sort is tolerating wrong answers, so the
    check feeds it wrong answers on purpose: 15% of comparisons are flipped.
    A comparison sort would be corrupted by the first one.
    """
    rng = random.Random(20260902)
    n, noise = 40, 0.15
    ids = [f"p{i}" for i in range(n)]
    truth = {pid: (n - i) / 5.0 for i, pid in enumerate(ids)}  # p0 strongest

    comparisons = []
    for _ in range(n * 12):
        a, b = rng.sample(ids, 2)
        better = a if truth[a] > truth[b] else b
        worse = b if better == a else a
        if rng.random() < noise:
            better, worse = worse, better
        comparisons.append({"winner": better, "loser": worse})

    ratings = fit_bradley_terry(ids, comparisons)
    order = sorted(ids, key=lambda pid: -ratings[pid])

    # Rank correlation against the truth, as plain Spearman.
    true_rank = {pid: i for i, pid in enumerate(ids)}
    d2 = sum((true_rank[pid] - i) ** 2 for i, pid in enumerate(order))
    rho = 1 - 6 * d2 / (n * (n * n - 1))
    assert rho > 0.9, f"recovered order only rho={rho:.3f} despite {noise:.0%} noise"
    assert order[0] in ids[:3], f"strongest player landed at {order.index(ids[0])}"

    # Every player unseen -> everyone ties at 0, nothing blows up.
    flat = fit_bradley_terry(ids, [])
    assert all(abs(v) < 1e-6 for v in flat.values()), "empty input should give a flat rating"

    # An undefeated player must stay finite (this is what REGULARIZATION buys).
    sweep = [{"winner": "p0", "loser": pid} for pid in ids[1:]]
    swept = fit_bradley_terry(ids, sweep)
    assert math.isfinite(swept["p0"]) and swept["p0"] == max(swept.values())

    # The round schedule only ever compares within a tier or across adjacent
    # tiers, so the global order has to come out of *chained* local answers --
    # p0 and p39 are never compared directly, and must still be ordered.
    tiers = [ids[i : i + 5] for i in range(0, n, 5)]
    chained = []
    for t, tier in enumerate(tiers):
        candidates = tier + (tiers[t - 1] if t else [])
        for _ in range(len(tier) * 8):
            a, b = rng.sample(candidates, 2)
            better = a if truth[a] > truth[b] else b
            chained.append({"winner": better, "loser": a if better == b else b})
    chain_ratings = fit_bradley_terry(ids, chained)
    chain_order = sorted(ids, key=lambda pid: -chain_ratings[pid])
    d2c = sum((true_rank[pid] - i) ** 2 for i, pid in enumerate(chain_order))
    rho_chain = 1 - 6 * d2c / (n * (n * n - 1))
    assert rho_chain > 0.95, f"chained tiers only recovered rho={rho_chain:.3f}"
    assert len(components(ids, chained)) == 1, "overlapping tiers should stay connected"

    # Tiers must stay in order relative to each other, or the finished queue
    # would shuffle rounds together. This is what fails when REGULARIZATION is
    # too strong for a local question schedule.
    medians = [sorted(chain_ratings[p] for p in tier)[len(tier) // 2] for tier in tiers]
    assert all(a > b for a, b in zip(medians, medians[1:])), (
        f"tier medians not monotonic: {[round(m, 2) for m in medians]}"
    )

    # And a split must be detected rather than silently fitted.
    split = [{"winner": ids[0], "loser": ids[1]}, {"winner": ids[20], "loser": ids[21]}]
    assert len([g for g in components(ids, split) if len(g) > 1]) == 2, "split not detected"

    # The failure that motivated round-blocking: a tail player with a thin but
    # perfect record must not be able to reach the top of the queue. Sorting by
    # raw rating puts him first; the round-blocked key must not.
    tail_rounds = {pid: 1 for pid in ids[:5]}
    tail_rounds.update({pid: 9 for pid in ids[5:]})
    lucky = ids[-1]
    ratings_hot = {pid: 0.0 for pid in ids}
    ratings_hot[lucky] = 9.0
    counts_thin = {pid: 8 for pid in ids}
    counts_thin[lucky] = 2
    assert max(ratings_hot, key=ratings_hot.get) == lucky, "setup: lucky should top raw rating"
    keyed = queue_order(tail_rounds, ratings_hot, counts_thin)
    assert min(keyed, key=keyed.get) != lucky, "thin tail player reached the top of the queue"
    assert keyed[lucky] > max(keyed[p] for p in ids[:5]), "round 9 outranked round 1"

    # But a well-evidenced player may still cross a round boundary -- past the
    # weaker half of the round above, not past all of it. A full slack of drift
    # reaches that round's centre, so the players it overtakes are the ones
    # their own answers pushed later.
    two_rounds = {pid: (1 if i < 10 else 2) for i, pid in enumerate(ids)}
    ratings_x = {pid: 0.0 for pid in ids}
    for i, pid in enumerate(ids[:10]):
        ratings_x[pid] = 1.0 - i * 0.4  # a real spread inside round 1
    ratings_x[ids[10]] = 6.0  # a round-2 player who beats everyone
    counts_full = {pid: 10 for pid in ids}
    crossed = queue_order(two_rounds, ratings_x, counts_full)
    weakest_r1 = max(crossed[p] for p in ids[:10])
    assert crossed[ids[10]] < weakest_r1, "no cross-round promotion possible"
    assert crossed[ids[10]] > min(crossed[p] for p in ids[:10]), "promotion jumped the whole round"

    assert [round_target(r) for r in (1, 2, 5, 10)] == [8, 7, 4, 2], "budget curve changed"
    assert adp_round(16.4, 10, 99) == 2 and adp_round(1.3, 10, 99) == 1
    assert adp_round(None, 10, 99) == 99, "missing ADP must fall to the back"
    # The cap: nothing sorts past the last round of the draft. Without it
    # Shrader (ADP 468) is round 47 and the Raiders (687) round 69, each alone
    # in a round the pair scheduler cannot draw a within-round pair from.
    assert adp_round(468.3, 10, 99) == 47, "setup: uncapped should overshoot"
    assert adp_round(468.3, 10, 99, last=16) == 16, "cap did not bind"
    assert adp_round(686.9, 10, 99, last=16) == 16
    assert adp_round(16.4, 10, 99, last=16) == 2, "cap must not touch a normal ADP"
    assert adp_round(None, 10, 99, last=16) == 16, "cap applies to the no-ADP fallback too"

    print(f"ok: rho={rho:.3f} at {noise:.0%} noise, chained tiers rho={rho_chain:.3f}, "
          f"splits detected, flat and undefeated finite")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", nargs="?", type=int, default=SNAKE_CONFIG.season)
    parser.add_argument("--pool", type=int, default=DEFAULT_POOL)
    parser.add_argument("--fit", action="store_true")
    parser.add_argument("--prefs", type=Path)
    parser.add_argument("--check", action="store_true")
    opts = parser.parse_args()

    if opts.check:
        demo()
    elif opts.fit:
        fit_and_write(opts.season, opts.prefs or prefs_path(opts.season))
    else:
        build_page(opts.season, opts.pool)


if __name__ == "__main__":
    main()
