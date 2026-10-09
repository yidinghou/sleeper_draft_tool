#!/usr/bin/env python3
"""Cancel every pending waiver claim of mine in ONE league (default: auction).

Uses Sleeper's private GraphQL `cancel_waiver_claim(league_id, leg, transaction_id)`
mutation, pulled from the public JS bundle the same way waiver_claim.py's
mutations were (see that module's docstring). Lists claims via check_waivers.

Dry run by default, --confirm to send. Always one league at a time.

Usage:
    python scripts/cancel_waivers.py [--league-id ID] [--confirm]
"""

from __future__ import annotations

import argparse
import sys

from check_waivers import build_query, describe
from waiver_claim import LEAGUE_CONFIG, post, read_token, resolve_my_roster_id


def cancel_payload(league_id: str, leg: int, transaction_id: str) -> dict:
    query = f"""mutation cancel_waiver_claim {{
        cancel_waiver_claim(league_id: "{league_id}", leg: {leg}, transaction_id: "{transaction_id}"){{
          status
          transaction_id
        }}
      }}"""
    return {"operationName": "cancel_waiver_claim", "variables": {}, "query": query}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", default=LEAGUE_CONFIG.league_id)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    token = read_token()
    if not token:
        sys.exit("no token: set $SLEEPER_TOKEN or write ~/.sleeper_token")
    roster_id = resolve_my_roster_id(args.league_id)
    result = post(build_query(args.league_id, roster_id, ["pending"]), token)
    txns = result["data"]["league_transactions_filtered"]
    print(f"{args.league_id}: {len(txns)} pending claims ({'CANCELLING' if args.confirm else 'dry run'})")
    for t in txns:
        print(f"  {describe(t)}  [{t['transaction_id']}]")
        if args.confirm:
            r = post(cancel_payload(args.league_id, t["leg"], t["transaction_id"]), token)
            print("    ->", r.get("errors") or r["data"]["cancel_waiver_claim"])


if __name__ == "__main__":
    main()
