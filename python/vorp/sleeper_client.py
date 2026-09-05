"""The Python half of `src/sleeper.ts`, name-for-name -- see
docs/spec/board/01-live-data-ingestion.md.

Read-only, stdlib-`urllib` only, so the pricing process needs no second
language runtime. Every GET is cache-busted the same way the TypeScript
client is: Sleeper's CDN caches `/draft` responses by hours, and a live
auction is stale the moment a cached response lands.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError

API_BASE = "https://api.sleeper.app/v1"


@dataclass(frozen=True)
class Nomination:
    player_id: Optional[str]
    nominating_slot: Optional[int]
    highest_offer: Optional[int]
    offering_slot: Optional[int]


def cache_busted_url(path: str, now: Callable[[], int] = lambda: int(time.time() * 1000)) -> str:
    """Sleeper's CDN caches aggressively, so every request gets a unique query
    param -- name-for-name the same helper `src/sleeper.ts` exports.
    """
    separator = "&" if "?" in path else "?"
    return f"{API_BASE}{path}{separator}_cb={now()}"


def _get(path: str) -> Any:
    request = urllib.request.Request(cache_busted_url(path), headers={"Cache-Control": "no-store"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Sleeper API {path} failed: {exc.code} {exc.reason}") from exc


def fetch_draft(draft_id: str) -> Dict[str, Any]:
    return _get(f"/draft/{draft_id}")


def fetch_draft_picks(draft_id: str) -> List[Dict[str, Any]]:
    return _get(f"/draft/{draft_id}/picks")


def fetch_league_users(league_id: str) -> List[Dict[str, Any]]:
    return _get(f"/league/{league_id}/users")


def draft_fingerprint(draft: Dict[str, Any]) -> str:
    """The cheap-poll signature: change means something worth an expensive
    `/picks` refetch happened. Unchanged means the poller can keep hitting
    the cheap `/draft` endpoint for free.
    """
    meta = draft.get("metadata") or {}
    return "|".join(
        str(v) if v is not None else ""
        for v in (
            draft.get("status"),
            meta.get("nominated_player_id"),
            meta.get("highest_offer"),
            meta.get("offering_slot"),
            meta.get("last_action_at"),
        )
    )


def parse_nomination(draft: Dict[str, Any]) -> Nomination:
    meta = draft.get("metadata") or {}
    nominating_slot = meta.get("nominating_slot")
    highest_offer = meta.get("highest_offer")
    offering_slot = meta.get("offering_slot")
    return Nomination(
        player_id=meta.get("nominated_player_id"),
        nominating_slot=int(nominating_slot) if nominating_slot is not None else None,
        highest_offer=int(highest_offer) if highest_offer is not None else None,
        offering_slot=int(offering_slot) if offering_slot is not None else None,
    )


def seat_identity(
    draft: Dict[str, Any],
    users: List[Dict[str, Any]],
    raw_picks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[int, Dict[str, Any]]:
    """`{seat_id: {user_id, username, display_name}}`, resolved from whatever
    the draft actually names a manager for. `seat_id` is 0-indexed, matching
    `LeagueState`'s seats everywhere else in this codebase -- Sleeper itself
    is 1-indexed (`draft_slot`, and a dict-shaped `draft_order`'s slot
    values), so every key below is shifted by one on the way in.

    `draft_order` seeds most of the map and comes in two shapes: a dict
    (`{user_id: slot}`, `slot` 1-indexed, the common case) or an array
    (`user_id` at index `slot - 1` -- i.e. the array index *is already* the
    0-indexed seat id -- with `None` for an unseeded slot). Picks are the
    fallback -- a seat `draft_order` never seeded can still have picked, via
    its `picked_by` -- and only fill a seat `draft_order` left open, never
    override it.
    """
    by_user_id = {u["user_id"]: u for u in users}

    def entry(user_id: str) -> Dict[str, Any]:
        user = by_user_id.get(user_id, {})
        return {
            "user_id": user_id,
            "username": user.get("username"),
            "display_name": user.get("display_name"),
        }

    identity: Dict[int, Dict[str, Any]] = {}
    draft_order = draft.get("draft_order")
    if isinstance(draft_order, dict):
        for user_id, slot in draft_order.items():
            if user_id is not None and slot is not None:
                identity[int(slot) - 1] = entry(user_id)
    elif isinstance(draft_order, list):
        for i, user_id in enumerate(draft_order):
            if user_id is not None:
                identity[i] = entry(user_id)

    for pick in raw_picks or []:
        slot = pick.get("draft_slot")
        user_id = pick.get("picked_by")
        if slot is not None and user_id and int(slot) - 1 not in identity:
            identity[int(slot) - 1] = entry(user_id)

    return identity


def sleeper_player_full_name(player: Dict[str, Any]) -> str:
    full_name = player.get("full_name")
    if full_name:
        return full_name
    return f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
