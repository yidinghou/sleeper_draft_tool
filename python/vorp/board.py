"""`04`'s pricing re-solved against the league that is actually left — see
docs/spec/vorp/07-live-draft-board.md.

`price_board` is lifted out of `scripts/draft_demo.py`'s `snapshot`, which
already did exactly this repricing for the scripted-draft demo; that script
now imports it from here instead of keeping its own copy. Nothing about the
computation changed — the model is not modified, it is handed a smaller
league (see `vorp.league.teams.LeagueState`).
"""

from __future__ import annotations

from typing import Dict, List

from .bid_value import apportion_with_floor
from .league.config import LeagueConfig
from .league.roster_fill import RosterFillPlayer as Player
from .league.teams import LeagueState
from .models import blend_weights


def ramp_weight(points: float, ramp: dict, w_floor: float) -> float:
    """Same formula `progressive_blend` uses -- the ramp only depends on the
    bars, so every price (shipped, VORP-only, VOLR-only) is this evaluated at
    a different `w_floor` over one solved fill, not a separate one.
    """
    top, bottom = ramp["top"], ramp["bottom"]
    if points >= top or top <= bottom:
        t = 1.0
    elif points <= bottom:
        t = 0.0
    else:
        t = (points - bottom) / (top - bottom)
    return w_floor + (1 - w_floor) * t


def price_board(
    state: LeagueState, remaining: List[Player], config: LeagueConfig, w_floor: float
) -> Dict:
    """Price, VORP $, and VOLR $ for every player still on the board, plus
    the residual league state behind them.

    The fill itself (`blend_weights`) is the expensive part -- it runs the
    league-wide matching plus one per-seat matching per seat. Solving it once
    and re-apportioning at three floor weights is what keeps repricing every
    remaining player, at every pick, fast enough for a live board.

    With nothing sold (`state = LeagueState.opening(config)`, `remaining` =
    the full board) this reproduces `blended_price.py`'s prices exactly at
    the same `w_floor` -- see `python/tests/test_board.py`.

    Drift (price minus opening price) isn't computed here: it needs an
    opening snapshot to diff against, which is a caller-held concern, not
    something a single solve has -- see how `scripts/draft_demo.py` tracks it
    across frames.
    """
    replacement, last_rostered, vorp_bar, volr_bar, ramps = blend_weights(
        remaining, config, state
    )
    starters = set(replacement.selected_player_ids)
    # Only players the full-roster fill actually seats get priced -- the same
    # restriction blended_price.py applies. Without it every player still in
    # the CSV gets a min_bid floor price, not just the ~192 with a roster
    # spot to be worth something in.
    drafted = set(last_rostered.selected_player_ids)
    pool = state.pool()
    spots_left = state.spots_left()

    def apportion_at(w_floor_: float):
        weights = {}
        for p in remaining:
            if p.player_id not in drafted:
                continue
            ramp = ramps.get(p.position)
            if ramp is None:
                continue
            w = ramp_weight(p.points, ramp, w_floor_)
            bar = w * ramp["replacement"] + (1 - w) * ramp["last_rostered"]
            weights[p.player_id] = max(0.0, p.points - bar)
        return apportion_with_floor(pool, weights, config.min_bid), weights

    prices, _ = apportion_at(w_floor)
    vorp_prices, vorp_weights = apportion_at(1.0)
    volr_prices, _ = apportion_at(0.0)

    # The exchange rate pure-VORP pricing actually runs on: after every priced
    # player is guaranteed min_bid, the rest of the pool splits in proportion
    # to points-over-replacement at this one rate.
    floor_total = len(vorp_weights) * config.min_bid
    total_margin = sum(vorp_weights.values())
    vorp_rate = (pool - floor_total) / total_margin if total_margin > 0 else 0.0

    rows = {}
    for p in remaining:
        pid = p.player_id
        if pid not in prices:
            continue
        rows[pid] = {
            "price": prices[pid],
            "vorp_dollar": vorp_prices.get(pid),
            "volr_dollar": volr_prices.get(pid),
            "is_starter": pid in starters,
            "vorp": round(p.points - vorp_bar.get(p.position, p.points), 1),
            "volr": round(p.points - volr_bar.get(p.position, p.points), 1),
        }
    return {
        "rows": rows,
        "vorp_rate": round(vorp_rate, 3),
        "levels": {
            pos: {
                "replacement": round(r["replacement"], 1),
                "last_rostered": round(r["last_rostered"], 1),
            }
            for pos, r in ramps.items()
        },
        "pool": pool,
        "spots_left": spots_left,
        "dollars_per_spot": round(pool / spots_left, 2) if spots_left else 0.0,
    }
