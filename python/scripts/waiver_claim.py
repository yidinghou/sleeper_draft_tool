#!/usr/bin/env python3
"""Claim a player through Sleeper's private GraphQL endpoint -- the same one
draft_pick.py uses for picks. The public v1 API has no write endpoints at all
(no waiver claim, no add/drop), so this talks to the endpoint the web app
itself calls. Captured by downloading the app's own JS bundle (a public,
unauthenticated static asset -- `https://sleepercdn.com/js/bundle-*.js`,
linked from any league page) and grepping it for `mutation submit_waiver_claim`
and `mutation league_create_transaction`.

The app picks between two mutations depending on whether the player is
currently on waivers or already a free agent:

    POST https://sleeper.com/graphql
    mutation submit_waiver_claim($k_adds: [String], $v_adds: [Int],
                                  $k_drops: [String], $v_drops: [Int],
                                  $k_settings: [String], $v_settings: [Int]) {
      submit_waiver_claim(league_id:"...", k_adds:$k_adds, v_adds:$v_adds,
                           k_drops:$k_drops, v_drops:$v_drops,
                           k_settings:$k_settings, v_settings:$v_settings) {...}
    }

    mutation league_create_transaction($k_adds: [String], $v_adds: [Int],
                                        $k_drops: [String], $v_drops: [Int]) {
      league_create_transaction(league_id:"...", type:"free_agent",
                                 k_adds:$k_adds, v_adds:$v_adds,
                                 k_drops:$k_drops, v_drops:$v_drops) {...}
    }

`k_adds`/`v_adds` and `k_drops`/`v_drops` are parallel arrays: keys are
player_ids, values are the claiming roster_id. `k_settings`/`v_settings`
carries the FAAB bid as `waiver_bid` -> amount, only sent for a waiver claim
in a FAAB league.

Undocumented and unversioned, same caveats as draft_pick.py: dry-run by
default, --confirm to send, not meant to run unattended.

Usage:
    python scripts/waiver_claim.py ADD_PLAYER_ID --drop DROP_PLAYER_ID --bid 5
    python scripts/waiver_claim.py ADD_PLAYER_ID --free-agent --confirm
    python scripts/waiver_claim.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.league.config import LEAGUE_CONFIG, MY_USERNAME  # noqa: E402
from vorp.sleeper_client import fetch_league_rosters, fetch_league_users  # noqa: E402

GRAPHQL = "https://sleeper.com/graphql"

#: See draft_pick.py -- same JWT, same lookup order.
TOKEN_FILE = Path.home() / ".sleeper_token"
AUTH_HEADER = "authorization"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Origin": "https://sleeper.com",
    "Referer": "https://sleeper.com/",
    "Accept": "application/json",
}

WAIVER_FIELDS = """adds
          consenter_ids
          created
          creator
          drops
          league_id
          leg
          metadata
          roster_ids
          settings
          status
          status_updated
          transaction_id
          type
          player_map"""


def build_payload(
    league_id: str,
    roster_id: int,
    add_player_id: str,
    drop_player_id: Optional[str] = None,
    bid: Optional[int] = None,
    free_agent: bool = False,
) -> dict:
    """Byte-shaped like the web app's own call -- see module docstring for
    where each mutation and field name was captured from.
    """
    k_adds, v_adds = [add_player_id], [roster_id]
    k_drops, v_drops = ([drop_player_id], [roster_id]) if drop_player_id else ([], [])
    variables = {"k_adds": k_adds, "v_adds": v_adds, "k_drops": k_drops, "v_drops": v_drops}

    if free_agent:
        query = f"""mutation league_create_transaction($k_adds: [String], $v_adds: [Int], $k_drops: [String], $v_drops: [Int]) {{
        league_create_transaction(league_id: "{league_id}", type: "free_agent", k_adds: $k_adds, v_adds: $v_adds, k_drops: $k_drops, v_drops: $v_drops){{
          {WAIVER_FIELDS}
        }}
      }}"""
        return {"operationName": "league_create_transaction", "variables": variables, "query": query}

    var_decl = "$k_adds: [String], $v_adds: [Int], $k_drops: [String], $v_drops: [Int]"
    args = "league_id: \"{}\", k_adds: $k_adds, v_adds: $v_adds, k_drops: $k_drops, v_drops: $v_drops".format(
        league_id
    )
    if bid is not None:
        var_decl += ", $k_settings: [String], $v_settings: [Int]"
        args += ", k_settings: $k_settings, v_settings: $v_settings"
        variables["k_settings"] = ["waiver_bid"]
        variables["v_settings"] = [bid]

    query = f"""mutation submit_waiver_claim({var_decl}) {{
        submit_waiver_claim({args}){{
          {WAIVER_FIELDS}
        }}
      }}"""
    return {"operationName": "submit_waiver_claim", "variables": variables, "query": query}


def read_token() -> Optional[str]:
    token = os.environ.get("SLEEPER_TOKEN")
    if token:
        return token.strip()
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip() or None
    return None


def resolve_my_roster_id(league_id: str) -> int:
    users = fetch_league_users(league_id)
    me = next(
        (
            u
            for u in users
            if (u.get("username") or "").lower() == MY_USERNAME.lower()
            or (u.get("display_name") or "").lower() == MY_USERNAME.lower()
        ),
        None,
    )
    if me is None:
        sys.exit(f"no league user matches MY_USERNAME={MY_USERNAME!r}")
    rosters = fetch_league_rosters(league_id)
    roster = next((r for r in rosters if r.get("owner_id") == me["user_id"]), None)
    if roster is None:
        sys.exit(f"no roster owned by user_id={me['user_id']}")
    return int(roster["roster_id"])


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
    payload = build_payload("123", 4, "8155", drop_player_id="9", bid=5)
    assert payload["operationName"] == "submit_waiver_claim"
    assert payload["variables"] == {
        "k_adds": ["8155"],
        "v_adds": [4],
        "k_drops": ["9"],
        "v_drops": [4],
        "k_settings": ["waiver_bid"],
        "v_settings": [5],
    }
    assert 'league_id: "123"' in payload["query"]
    assert "{{" not in payload["query"] and "}}" not in payload["query"]

    fa_payload = build_payload("123", 4, "8155", free_agent=True)
    assert fa_payload["operationName"] == "league_create_transaction"
    assert fa_payload["variables"]["k_drops"] == []
    assert 'type: "free_agent"' in fa_payload["query"]
    print("ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("add_player_id", nargs="?")
    parser.add_argument("--league-id", default=LEAGUE_CONFIG.league_id)
    parser.add_argument("--drop", dest="drop_player_id", help="player_id to drop, if any")
    parser.add_argument("--bid", type=int, help="FAAB bid amount (waiver claims only)")
    parser.add_argument(
        "--free-agent",
        action="store_true",
        help="use the free-agent add/drop mutation instead of a waiver claim",
    )
    parser.add_argument("--confirm", action="store_true", help="actually send it")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.add_player_id:
        parser.error("add_player_id is required")

    roster_id = resolve_my_roster_id(args.league_id)
    payload = build_payload(
        args.league_id,
        roster_id,
        args.add_player_id,
        drop_player_id=args.drop_player_id,
        bid=args.bid,
        free_agent=args.free_agent,
    )

    if not args.confirm:
        print(f"DRY RUN -- would claim player {args.add_player_id} for roster {roster_id}")
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
