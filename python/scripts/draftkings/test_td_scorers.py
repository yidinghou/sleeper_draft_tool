"""Self-check for td_scorers.py's regex parser against a real saved page."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from td_scorers import build_index, parse_td_scorers, to_records  # noqa: E402
from vorp.sources.sleeper import fetch_players_nfl, sleeper_player_full_name  # noqa: E402

FIXTURE = list(Path.home().glob("Downloads/*DraftKings Sportsbook.html"))


def test_parses_known_row() -> None:
    assert FIXTURE, "no saved DraftKings page found in ~/Downloads to test against"
    html = FIXTURE[0].read_text(encoding="utf-8", errors="ignore")
    games = parse_td_scorers(html)
    assert games, "parsed zero games -- DraftKings markup likely changed"

    # Odds move day to day, so check shape (a known player has all 3 markets
    # as ints) rather than pinning exact values that will go stale.
    gibbs = next(
        p for g in games for p in g["players"] if p["name"] == "Jahmyr Gibbs"
    )
    assert all(isinstance(gibbs[k], int) for k in ("anytime", "first", "two_plus"))


def test_matches_players_to_sleeper_ids() -> None:
    assert FIXTURE, "no saved DraftKings page found in ~/Downloads to test against"
    html = FIXTURE[0].read_text(encoding="utf-8", errors="ignore")
    games = parse_td_scorers(html)
    players = fetch_players_nfl()
    records = to_records(games, players, build_index(players))

    total = sum(len(g["players"]) for g in games)
    matched = sum(1 for r in records.values() if r["player_id"])
    assert matched / total > 0.9, f"only {matched}/{total} players matched a player_id"

    # Look the real id up from the cache rather than hardcoding it, so this
    # survives Sleeper reassigning ids.
    gibbs_id = next(
        pid for pid, p in players.items() if sleeper_player_full_name(p) == "Jahmyr Gibbs"
    )
    assert records[gibbs_id]["dk_name"] == "Jahmyr Gibbs"


if __name__ == "__main__":
    test_parses_known_row()
    test_matches_players_to_sleeper_ids()
    print("ok")
