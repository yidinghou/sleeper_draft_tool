#!/usr/bin/env python3
"""List pending waiver claims through Sleeper's private GraphQL endpoint.

The public v1 API's `GET /league/{id}/transactions/{week}` never returns
`pending` transactions -- only ones already resolved (`complete`/`failed`).
So it can't answer "what waivers do I have in right now"; it silently looks
like zero. The real answer lives behind the same private, authenticated
GraphQL endpoint `waiver_claim.py` uses to submit claims (see that module's
docstring), via a query the web app calls `league_transactions_filtered`
-- found the same way, by grepping Sleeper's public JS bundle
(`https://sleepercdn.com/js/bundle-*.js`) for `league_transactions_filtered`.

    query league_transactions_filtered {
      league_transactions_filtered(league_id: "...", roster_id_filters: [...],
                                    type_filters: [...], leg_filters: [...],
                                    status_filters: ["pending"]) { ... }
    }

Read-only -- no --confirm gate needed, this never mutates anything.

Usage:
    python scripts/check_waivers.py                    # both leagues, my roster
    python scripts/check_waivers.py --league-id 123...  # one league
    python scripts/check_waivers.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vorp.league.config import LEAGUE_CONFIG, SNAKE_CONFIG  # noqa: E402
from waiver_claim import GRAPHQL, BROWSER_HEADERS, AUTH_HEADER, read_token, resolve_my_roster_id, post  # noqa: E402

FIELDS = """adds
          drops
          leg
          roster_ids
          settings
          status
          transaction_id
          type
          player_map"""


def build_query(league_id: str, roster_id: int, status_filters: list[str]) -> dict:
    query = f"""query league_transactions_filtered {{
      league_transactions_filtered(league_id: "{league_id}", roster_id_filters: {json.dumps([roster_id])},
                                    type_filters: [], leg_filters: [], status_filters: {json.dumps(status_filters)}) {{
        {FIELDS}
      }}
    }}"""
    return {"operationName": "league_transactions_filtered", "variables": {}, "query": query}


def describe(txn: dict) -> str:
    pm = txn.get("player_map") or {}

    def name(player_id: str) -> str:
        p = pm.get(player_id)
        if p:
            return f"{p['first_name']} {p['last_name']} ({p['position']})"
        return player_id  # team defense id (e.g. "SF") has no player_map entry

    adds = ", ".join(f"+{name(pid)}" for pid in (txn.get("adds") or {}))
    drops = ", ".join(f"-{name(pid)}" for pid in (txn.get("drops") or {}))
    bid = (txn.get("settings") or {}).get("waiver_bid", 0)
    return f"{adds} / {drops}  bid=${bid}" if drops else f"{adds}  bid=${bid}"


def selftest() -> None:
    q = build_query("123", 4, ["pending"])
    assert q["operationName"] == "league_transactions_filtered"
    assert 'league_id: "123"' in q["query"]
    assert "roster_id_filters: [4]" in q["query"]
    assert 'status_filters: ["pending"]' in q["query"]

    fake = {
        "adds": {"8155": 4},
        "drops": {"9": 4},
        "settings": {"waiver_bid": 5},
        "player_map": {
            "8155": {"first_name": "A", "last_name": "Add", "position": "RB"},
            "9": {"first_name": "B", "last_name": "Drop", "position": "WR"},
        },
    }
    assert describe(fake) == "+A Add (RB) / -B Drop (WR)  bid=$5"
    print("ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", action="append", dest="league_ids")
    parser.add_argument("--status", default="pending", help="comma-separated statuses (default: pending)")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    league_ids = args.league_ids or [LEAGUE_CONFIG.league_id, SNAKE_CONFIG.league_id]
    status_filters = args.status.split(",")

    token = read_token()
    if not token:
        sys.exit(f"no token: set $SLEEPER_TOKEN or write ~/.sleeper_token")

    for league_id in league_ids:
        roster_id = resolve_my_roster_id(league_id)
        result = post(build_query(league_id, roster_id, status_filters), token)
        if result.get("errors"):
            sys.exit(f"rejected: {json.dumps(result['errors'])}")
        txns = result["data"]["league_transactions_filtered"]
        print(f"=== {league_id} (roster {roster_id}): {len(txns)} {'/'.join(status_filters)} ===")
        for t in txns:
            print(f"  {describe(t)}")


if __name__ == "__main__":
    main()
