"""Principles: what any auction valuation model has to satisfy, written as
executable checks so a model is judged rather than argued about.

Two kinds, and the distinction matters:

  LAW          A property that must hold or the output isn't a price list.
               Violating one is a bug, no matter how good the numbers look.
               Laws are pass/fail and they don't negotiate.

  CALIBRATION  A property that says the model matches the world. Graded, not
               pass/fail, and reasonable models disagree here. A calibration
               failure is a finding to look at, not a defect to fix blindly
               -- the market can be wrong and the point of the model is to
               say so.

The laws are lifted from the "Done when" sections of docs/spec/vorp/01-03,
which already stated them in prose; this module makes them run. The
mid-draft law is the one those specs never claimed and no current model
survives -- see `survives_mid_draft`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Sequence

from .league_config import FLEX_ELIGIBILITY, POSITIONS, STREAMING_POSITIONS, LeagueConfig
from .models import Model, Player, Valuation

LAW = "law"
CALIBRATION = "calibration"


@dataclass(frozen=True)
class Context:
    """Everything a principle is allowed to look at."""

    players: List[Player]
    config: LeagueConfig
    #: player_id -> the market's own auction value, where known.
    market: Dict[str, int]

    def by_id(self) -> Dict[str, Player]:
        return {p.player_id: p for p in self.players}


@dataclass(frozen=True)
class Finding:
    passed: bool
    detail: str
    #: A number worth trending across models, when the check produces one.
    measure: Optional[float] = None


@dataclass(frozen=True)
class Principle:
    id: str
    kind: str
    statement: str
    #: Takes the model itself, not just one output, so a principle is free to
    #: re-run it against a different board -- which is the only way to state
    #: anything about mid-draft behaviour.
    check: Callable[[Model, Context], Finding]


# --------------------------------------------------------------------------
# Laws
# --------------------------------------------------------------------------


def _value(model: Model, ctx: Context) -> Valuation:
    return model(ctx.players, ctx.config)


def reconciles(model: Model, ctx: Context) -> Finding:
    v = _value(model, ctx)
    total = ctx.config.teams * ctx.config.budget
    got = sum(v.prices.values())
    return Finding(
        passed=got == total,
        detail=f"prices sum to ${got}, budget is ${total}",
        measure=got - total,
    )


def monotonic_within_position(model: Model, ctx: Context) -> Finding:
    v = _value(model, ctx)
    by_id = ctx.by_id()
    groups: Dict[str, List[str]] = {}
    for pid in v.prices:
        groups.setdefault(by_id[pid].position, []).append(pid)

    violations = []
    for position, pids in groups.items():
        ranked = sorted(pids, key=lambda pid: (-by_id[pid].points, pid))
        for better, worse in zip(ranked, ranked[1:]):
            if v.prices[worse] > v.prices[better]:
                violations.append(
                    f"{position}: {worse} ${v.prices[worse]} > {better} ${v.prices[better]}"
                )
    return Finding(
        passed=not violations,
        detail="no player out-prices a higher scorer at his position"
        if not violations
        else f"{len(violations)} crossings, worst: {violations[0]}",
        measure=len(violations),
    )


def respects_the_floor(model: Model, ctx: Context) -> Finding:
    v = _value(model, ctx)
    below = [pid for pid, price in v.prices.items() if price < ctx.config.min_bid]
    return Finding(
        passed=not below,
        detail=f"every price >= ${ctx.config.min_bid}"
        if not below
        else f"{len(below)} priced below the floor",
        measure=len(below),
    )


def fills_every_roster_spot(model: Model, ctx: Context) -> Finding:
    """A price list that names fewer players than the league drafts leaves
    somebody unable to fill a roster.
    """
    v = _value(model, ctx)
    want = ctx.config.teams * ctx.config.roster_size
    got = len(v.prices)
    return Finding(
        passed=got == want,
        detail=f"{got} players priced, league drafts {want}",
        measure=got - want,
    )


def prices_no_undraftable_position(model: Model, ctx: Context) -> Finding:
    """A position the roster template never plays anywhere (K, here) must be
    absent, not priced at zero. Absent is a claim; $0 is a number nobody can
    bid.
    """
    v = _value(model, ctx)
    by_id = ctx.by_id()
    draftable = set(ctx.config.draftable_positions())
    strays = {by_id[pid].position for pid in v.prices} - draftable
    return Finding(
        passed=not strays,
        detail="only draftable positions are priced"
        if not strays
        else f"priced positions outside the template: {sorted(strays)}",
        measure=len(strays),
    )


def never_benches_a_streamed_position(model: Model, ctx: Context) -> Finding:
    """Positions real managers stream off waivers get exactly one per team --
    no bench depth, however the projections rate a backup.
    """
    v = _value(model, ctx)
    by_id = ctx.by_id()
    offenders = []
    for position in STREAMING_POSITIONS:
        count = sum(1 for pid in v.prices if by_id[pid].position == position)
        if count > ctx.config.teams:
            offenders.append(f"{position}: {count} priced, {ctx.config.teams} teams")
    return Finding(
        passed=not offenders,
        detail="streamed positions get one per team"
        if not offenders
        else "; ".join(offenders),
        measure=len(offenders),
    )


def ordering_carries_information(model: Model, ctx: Context) -> Finding:
    """If the min_bid floors eat most of a pool, the prices in it are floor
    plus rounding noise, and their ordering means nothing. A model may put
    the whole bench at the floor deliberately -- that's an honest claim, and
    it declares it by ranking the bench instead of pricing it.
    """
    v = _value(model, ctx)
    priced_above_floor = sum(1 for p in v.prices.values() if p > ctx.config.min_bid)
    share = priced_above_floor / max(1, len(v.prices))
    ranks_bench = len(v.bench_order) == len(v.bench)
    passed = share >= 0.5 or ranks_bench
    return Finding(
        passed=passed,
        detail=f"{share:.0%} of priced players are above the floor"
        + ("; bench is ranked" if ranks_bench else "; bench is neither priced nor ranked"),
        measure=share,
    )


def indifferent_to_a_constant_shift(model: Model, ctx: Context) -> Finding:
    """Add the same number of points to every projection on the board. No
    draft decision changes -- every player's margin over every other player
    is what it was, and the optimal fill picks the identical set, because a
    constant times a fixed number of slots is a constant. So no price may
    move.

    This is the founding claim of a baseline model, stated as a property:
    value is margin over what's freely available, never raw production. A
    model that fails this is pricing the units the projections happen to be
    denominated in.
    """
    before = _value(model, ctx)
    shifted = replace(
        ctx,
        players=[
            type(p)(player_id=p.player_id, position=p.position, points=p.points + 50.0)
            for p in ctx.players
        ],
    )
    after = model(shifted.players, shifted.config)

    moved = [
        pid
        for pid in before.prices
        if before.prices.get(pid) != after.prices.get(pid)
    ]
    biggest = max(
        (abs(before.prices[pid] - after.prices.get(pid, 0)) for pid in moved),
        default=0,
    )
    return Finding(
        passed=not moved,
        detail="every price unchanged under a +50 shift"
        if not moved
        else f"{len(moved)} prices moved, largest by ${biggest}",
        measure=len(moved),
    )


def ramp_slope_is_safe(model: Model, ctx: Context) -> Finding:
    """A model that slides its bar as points fall must slide it slower than
    the points themselves.

    Margin is `points - bar(points)`, so it rises with points only while
    `d(bar)/d(points) <= 1`. For a ramp between the two solved levels that
    derivative is `(replacement - last_rostered) / ramp_span`, and the
    condition becomes: **the ramp must span at least as many points as the
    gap between the two bars it slides between.**

    This is `monotonic` stated structurally rather than observed. `monotonic`
    finds a crossing on one board; this says the crossing cannot happen on
    any board, which is what makes the guarantee worth relying on. A model
    that doesn't ramp at all trivially satisfies it.
    """
    from .models import DEFAULT_FULL_WEIGHT_SHARE, DEFAULT_W_FLOOR, blend_weights

    *_, ramps = blend_weights(
        ctx.players, ctx.config, DEFAULT_FULL_WEIGHT_SHARE, DEFAULT_W_FLOOR
    )
    tight = []
    worst = None
    for position, ramp in ramps.items():
        gap = ramp["replacement"] - ramp["last_rostered"]
        span = ramp["top"] - ramp["bottom"]
        if gap <= 0:
            continue
        headroom = span / gap
        if worst is None or headroom < worst[1]:
            worst = (position, headroom)
        if headroom < 1.0:
            tight.append(f"{position}: span {span:.1f} < bar gap {gap:.1f}")
    return Finding(
        passed=not tight,
        detail=f"tightest headroom {worst[1]:.2f}x at {worst[0]}"
        if worst and not tight
        else ("; ".join(tight) if tight else "model does not ramp"),
        measure=round(worst[1], 2) if worst else None,
    )


def survives_mid_draft(model: Model, ctx: Context) -> Finding:
    """Rerun the model mid-draft. Every position that still has players
    available and slots open must still be priceable.

    Checked at two states, because the easy one hides the real bug:

      - a quarter sold, where starting slots are still plentiful; and
      - the state where one position's starting slots are fully consumed,
        which is what made `draftable_positions()` collapse and price every
        remaining receiver at nothing.

    A model whose positions silently go unreachable mid-draft tells you a
    quarterback is worth nothing at the exact moment four teams still need
    one.
    """
    problems = []
    for fraction in (0.25, 0.55):
        sold, residual = mid_draft_state(ctx, fraction=fraction)
        remaining = [p for p in ctx.players if p.player_id not in sold]
        try:
            v = model(remaining, residual)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{fraction:.0%}: raised {type(exc).__name__}: {exc}")
            continue

        by_id = {p.player_id: p for p in remaining}
        priced = {by_id[pid].position for pid in v.prices}
        # Reachability is judged against the ORIGINAL template: consuming a
        # position's starting slots means the league needs fewer of them, not
        # that the position stopped existing.
        still_open = {
            pos
            for pos in ctx.config.draftable_positions()
            if any(p.position == pos for p in remaining)
        }
        missing = sorted(still_open - priced)
        if missing:
            problems.append(f"{fraction:.0%} sold: unpriceable {missing}")

    return Finding(
        passed=not problems,
        detail="priceable at 25% and 55% sold" if not problems else "; ".join(problems),
        measure=len(problems),
    )


# --------------------------------------------------------------------------
# Calibrations
# --------------------------------------------------------------------------


def agrees_with_the_market(model: Model, ctx: Context) -> Finding:
    """Mean absolute error against the market's own auction values. Not a
    law: the whole reason to build a model is to disagree with the market
    somewhere. A large error is a question ("where, and why?"), not a defect.
    """
    v = _value(model, ctx)
    pairs = [(price, ctx.market[pid]) for pid, price in v.prices.items() if pid in ctx.market]
    if not pairs:
        return Finding(False, "no market prices to compare against")
    mae = sum(abs(a - b) for a, b in pairs) / len(pairs)
    return Finding(
        passed=mae <= 4.0,
        detail=f"MAE ${mae:.2f} across {len(pairs)} players",
        measure=round(mae, 2),
    )


def spends_like_the_room_on_the_bench(model: Model, ctx: Context) -> Finding:
    """How much of a team's budget lands outside the starting lineup, against
    what the market actually puts there. A model that wants $38 on the bench
    when the room spends $12 isn't wrong, but it is making a large claim and
    should be made to say so out loud.
    """
    v = _value(model, ctx)
    modelled = sum(v.prices[pid] for pid in v.bench if pid in v.prices) / ctx.config.teams
    market_bench = sum(ctx.market.get(pid, 0) for pid in v.bench) / ctx.config.teams
    return Finding(
        passed=abs(modelled - market_bench) <= 6.0,
        detail=f"${modelled:.1f}/team on the bench, market puts ${market_bench:.1f}",
        measure=round(modelled - market_bench, 1),
    )


def tops_out_where_the_market_does(model: Model, ctx: Context) -> Finding:
    """The most expensive player. A model that can't afford the board's best
    player, or wants to spend a third of a budget on him, is mis-scaled at
    the top even if it reconciles overall.
    """
    v = _value(model, ctx)
    top = max(v.prices.values())
    market_top = max(ctx.market.values()) if ctx.market else 0
    return Finding(
        passed=abs(top - market_top) <= 15,
        detail=f"top price ${top}, market top ${market_top}",
        measure=top - market_top,
    )


# --------------------------------------------------------------------------
# Mid-draft state
# --------------------------------------------------------------------------


def mid_draft_state(ctx: Context, fraction: float):
    """Sell off the top `fraction` of the board in market order, consuming one
    slot per sale: a concrete slot at that position if any remain, else a
    flex he's eligible for, else a bench slot.

    The consumption rule is an assumption, and a live tool would replace it
    with the real per-seat roster state. It is deliberately the *friendly*
    assumption -- starters fill first, which is how the room actually drafts
    -- so a model that fails here fails on easy mode.
    """
    by_id = ctx.by_id()
    order = [pid for pid in sorted(ctx.market, key=lambda p: -ctx.market[p]) if pid in by_id]
    count = int(len(ctx.players) and fraction * ctx.config.teams * ctx.config.roster_size)

    starting = {k: v * ctx.config.teams for k, v in ctx.config.starting_slots.items()}
    flex = {k: v * ctx.config.teams for k, v in ctx.config.flex_slots.items()}
    bench = ctx.config.bench_slots * ctx.config.teams
    spent = 0
    sold = set()

    for pid in order[:count]:
        position = by_id[pid].position
        if starting.get(position, 0) > 0:
            starting[position] -= 1
        else:
            for name, left in flex.items():
                if left > 0 and position in FLEX_ELIGIBILITY[name]:
                    flex[name] -= 1
                    break
            else:
                bench = max(0, bench - 1)
        spent += ctx.market[pid]
        sold.add(pid)

    money_left = ctx.config.teams * ctx.config.budget - spent
    residual = replace(
        ctx.config,
        budget=max(ctx.config.min_bid, money_left // ctx.config.teams),
        starting_slots={k: v // ctx.config.teams for k, v in starting.items()},
        flex_slots={k: v // ctx.config.teams for k, v in flex.items()},
        bench_slots=bench // ctx.config.teams,
        # Slots get consumed; the set of positions the league plays does not.
        # Without this the residual template would claim a position whose
        # starting slots are all spoken for is one the league never plays.
        plays_positions=tuple(ctx.config.draftable_positions()),
    )
    return sold, residual


# --------------------------------------------------------------------------
# The suite
# --------------------------------------------------------------------------

PRINCIPLES: Sequence[Principle] = (
    Principle(
        "reconciles",
        LAW,
        "Prices sum to exactly teams x budget -- every dollar in the room is allocated once.",
        reconciles,
    ),
    Principle(
        "monotonic",
        LAW,
        "Within a position, no player out-prices someone who scores more than he does.",
        monotonic_within_position,
    ),
    Principle(
        "floor",
        LAW,
        "Every priced player is worth at least min_bid -- $0 is not a bid.",
        respects_the_floor,
    ),
    Principle(
        "fills-rosters",
        LAW,
        "Exactly as many players are priced as the league actually drafts.",
        fills_every_roster_spot,
    ),
    Principle(
        "no-phantom-positions",
        LAW,
        "A position the roster template never plays is absent, not priced.",
        prices_no_undraftable_position,
    ),
    Principle(
        "no-streamed-depth",
        LAW,
        "A streamed position gets one per team and no bench depth.",
        never_benches_a_streamed_position,
    ),
    Principle(
        "informative-ordering",
        LAW,
        "Prices are mostly above the floor, or the model ranks what it won't price.",
        ordering_carries_information,
    ),
    Principle(
        "baseline-not-points",
        LAW,
        "Adding a constant to every projection changes no price -- value is margin, not production.",
        indifferent_to_a_constant_shift,
    ),
    Principle(
        "ramp-slope",
        LAW,
        "A sliding bar slides slower than points do -- the ramp spans at least the gap between its two bars.",
        ramp_slope_is_safe,
    ),
    Principle(
        "mid-draft",
        LAW,
        "Mid-draft, every position with players and slots left is still priceable.",
        survives_mid_draft,
    ),
    Principle(
        "market-mae",
        CALIBRATION,
        "Mean absolute error against the market's own auction values.",
        agrees_with_the_market,
    ),
    Principle(
        "bench-spend",
        CALIBRATION,
        "Dollars per team outside the starting lineup, against what the room spends there.",
        spends_like_the_room_on_the_bench,
    ),
    Principle(
        "top-price",
        CALIBRATION,
        "The most expensive player lands near where the market tops out.",
        tops_out_where_the_market_does,
    ),
)


@dataclass(frozen=True)
class Report:
    model_name: str
    findings: Dict[str, Finding]

    def laws_passed(self, principles: Sequence[Principle] = PRINCIPLES) -> int:
        return sum(
            1 for p in principles if p.kind == LAW and self.findings[p.id].passed
        )

    def laws_total(self, principles: Sequence[Principle] = PRINCIPLES) -> int:
        return sum(1 for p in principles if p.kind == LAW)


def _memoized(model: Model) -> Model:
    """Most principles ask the model the same question -- price this board --
    and each answer costs two optimal fills. Cache by board identity so the
    suite pays once per distinct board instead of once per principle. The
    cache holds its keys' objects alive, so a recycled id() can't collide.
    """
    cache: Dict[tuple, tuple] = {}

    def wrapped(players: List[Player], config: LeagueConfig) -> Valuation:
        key = (id(players), id(config))
        if key not in cache:
            cache[key] = (players, config, model(players, config))
        return cache[key][2]

    return wrapped


def run(model: Model, ctx: Context, principles: Sequence[Principle] = PRINCIPLES) -> Report:
    cached = _memoized(model)
    findings = {}
    for principle in principles:
        try:
            findings[principle.id] = principle.check(cached, ctx)
        except Exception as exc:  # noqa: BLE001
            findings[principle.id] = Finding(False, f"raised {type(exc).__name__}: {exc}")
    return Report(model_name=cached(ctx.players, ctx.config).name, findings=findings)
