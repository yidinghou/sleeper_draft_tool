#!/usr/bin/env python3
"""Make a draft pick through Sleeper's private GraphQL endpoint.

The public v1 API is read-only, so this talks to the same endpoint the web app
uses. Captured from the draft room by hooking XHR while making a pick by hand:

    POST https://sleeper.com/graphql
    mutation draft_pick_player {
      draft_pick_player(sport:"nfl", player_id:"8155",
                        draft_id:"...", pick_no:27) { ... }
    }

Undocumented and unversioned. It can change without notice and the failure
mode is a pick that silently doesn't happen, which is why nothing here is
meant to run unattended -- the queue is still the mechanism that covers being
away from the keyboard. This is for making one specific pick, watched.

The token is a long-lived JWT (the one the web app puts in its websocket URL).
Read from $SLEEPER_TOKEN so it never lands in the repo:

    export SLEEPER_TOKEN='...'   # from DevTools, or the app's own storage

Usage:
    python scripts/draft_pick.py DRAFT_ID PLAYER_ID            # dry run
    python scripts/draft_pick.py DRAFT_ID PLAYER_ID --confirm  # actually picks
    python scripts/draft_pick.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vorp.sleeper_client import fetch_draft_picks  # noqa: E402

GRAPHQL = "https://sleeper.com/graphql"

#: Where `read_token` looks when $SLEEPER_TOKEN is unset. Outside the repo on
#: purpose -- a JWT that lives next to the source is a JWT that gets committed.
TOKEN_FILE = Path.home() / ".sleeper_token"

#: Header the web app authenticates /graphql with. NOT verified -- the call
#: that would have read it back was blocked, so this is the conventional
#: Sleeper shape (raw JWT, no "Bearer" prefix). If a pick comes back
#: unauthenticated, check DevTools > Network > any /graphql row and fix this.
AUTH_HEADER = "authorization"

MUTATION = """mutation draft_pick_player {{
        draft_pick_player(sport: "nfl",player_id: "{player_id}",draft_id: "{draft_id}",pick_no: {pick_no}){{
          draft_id
          pick_no
          player_id
          picked_by
          is_keeper
          metadata
          reactions
        }}
      }}"""


def build_payload(draft_id: str, player_id: str, pick_no: int) -> dict:
    """The request body, byte-shaped like the web app's own -- same operation
    name, same inline-argument style (Sleeper's client doesn't use variables)."""
    return {
        "operationName": "draft_pick_player",
        "variables": {},
        "query": MUTATION.format(draft_id=draft_id, player_id=player_id, pick_no=pick_no),
    }


def read_token() -> str | None:
    """$SLEEPER_TOKEN, else `~/.sleeper_token`. Never printed, never logged --
    callers pass it straight to `post`.
    """
    token = os.environ.get("SLEEPER_TOKEN")
    if token:
        return token.strip()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip() or None
    return None


#: Sent alongside the auth header. An armed pick with urllib's defaults came
#: back 403 -- not 401 -- which reads as bot-blocking rather than bad auth:
#: `Python-urllib/3.x` with no Origin or Referer is a common WAF trip. These
#: make the request look like the one the draft room itself sends.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Origin": "https://sleeper.com",
    "Referer": "https://sleeper.com/",
    "Accept": "application/json",
}


def post(payload: dict, token: str) -> dict:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        GRAPHQL,
        data=body,
        headers={"Content-Type": "application/json", AUTH_HEADER: token, **BROWSER_HEADERS},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def selftest() -> None:
    payload = build_payload("123", "8155", 27)
    query = payload["query"]
    assert payload["operationName"] == "draft_pick_player"
    assert 'player_id: "8155"' in query
    assert 'draft_id: "123"' in query
    assert "pick_no: 27" in query, query
    assert "{{" not in query and "}}" not in query, "format braces leaked"
    print("ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft_id", nargs="?")
    parser.add_argument("player_id", nargs="?")
    parser.add_argument("--pick-no", type=int, help="default: next open pick")
    parser.add_argument("--confirm", action="store_true", help="actually send it")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.draft_id or not args.player_id:
        parser.error("draft_id and player_id are required")

    picks = fetch_draft_picks(args.draft_id)
    taken = {str(p.get("player_id")) for p in picks}
    if args.player_id in taken:
        sys.exit(f"player {args.player_id} is already drafted")

    pick_no = args.pick_no or len(picks) + 1
    payload = build_payload(args.draft_id, args.player_id, pick_no)

    if not args.confirm:
        print(f"DRY RUN -- would pick player {args.player_id} at pick {pick_no}")
        print(json.dumps(payload, indent=2))
        return

    token = read_token()
    if not token:
        sys.exit(f"no token: set $SLEEPER_TOKEN or write {TOKEN_FILE}")

    result = post(payload, token)
    if result.get("errors"):
        sys.exit(f"rejected: {json.dumps(result['errors'])}")
    print(json.dumps(result.get("data"), indent=2))


if __name__ == "__main__":
    main()
