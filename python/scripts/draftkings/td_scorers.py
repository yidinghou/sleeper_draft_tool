#!/usr/bin/env python3
"""Mirror DraftKings' NFL TD-scorer prop board from a saved copy of the page.

DraftKings' odds API 403s scripted requests (Akamai bot protection), and the
sportsbook domain is blocked for browser automation -- so there is no live
fetch here. Instead: save the page yourself (Cmd+S -> "Webpage, Complete")
and pass the saved .html to this script. Chrome's complete-page save captures
the fully-rendered DOM, which holds the whole odds board as static markup
even though the page's own JSON state is empty at save time.

Usage: python scripts/draftkings/td_scorers.py <path to saved .html>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from html_page import write_local  # noqa: E402
from vorp.sources.sleeper import fetch_players_nfl  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
HTML_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "td_scorers.html"

#: DK's TD-scorer board only ever lists offensive skill positions.
OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE", "FB"}
SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")
NON_LETTER_RE = re.compile(r"[^a-z]")

MARKET_NAMES = ("anytime", "first", "two_plus")

# ponytail: regex over DraftKings' rendered markup, not a real HTML parser --
# the structure is flat and was verified against a real saved page (390
# player rows). If DraftKings changes their class names this will silently
# return zero rows; re-derive the patterns from a fresh saved file if so.
MATCHUP_RE = re.compile(
    r'<span class="cb-title__left-team"><img[^>]*>\s*'
    r'<span class="cb-title__team-name">([^<]+)</span></span>'
    r'<span class="cb-title__separator">at</span>'
    r'<span class="cb-title__right-team"><span class="cb-title__team-name">([^<]+)</span>'
)
NAME_RE = re.compile(
    r'cb-player-page-link" data-testid="player-page-link">.*?'
    r'<p class="cb-market__label--truncate-strings">([^<]+)</p>',
    re.S,
)
BUTTON_RE = re.compile(
    r'<button[^>]*class="cb-market__button cb-market__button--(regular|empty)"[^>]*>(.*?)</button>',
    re.S,
)
ODDS_RE = re.compile(r'cb-market__button-odds"[^>]*>([^<]+)</span>')


def parse_odds(text: str) -> int | None:
    return int(text.replace("−", "-")) if text else None


def button_odds(chunk: str) -> list[int | None]:
    """First 3 market buttons following a player's name, in column order."""
    markets = []
    for kind, body in BUTTON_RE.findall(chunk)[:3]:
        markets.append(None if kind == "empty" else parse_odds(ODDS_RE.search(body)[1] if ODDS_RE.search(body) else None))
    markets += [None] * (3 - len(markets))
    return markets


def parse_td_scorers(html: str) -> list[dict]:
    markers = [(m.start(), "game", m) for m in MATCHUP_RE.finditer(html)]
    markers += [(m.start(), "player", m) for m in NAME_RE.finditer(html)]
    markers.sort(key=lambda t: t[0])

    games: list[dict] = []
    current = None
    for i, (pos, kind, m) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(html)
        if kind == "game":
            current = {"away": m[1], "home": m[2], "players": []}
            games.append(current)
        elif current is not None:
            anytime, first, two_plus = button_odds(html[m.end():end])
            current["players"].append(
                {"name": m[1], "anytime": anytime, "first": first, "two_plus": two_plus}
            )
    return [g for g in games if g["players"]]


def normalize_name(name: str) -> str:
    """Same join key Sleeper computes into `search_full_name` -- lowercase,
    suffix stripped, letters only -- so DK names line up with it directly.
    """
    return NON_LETTER_RE.sub("", SUFFIX_RE.sub("", name.lower()))


def build_index(players: dict[str, dict]) -> dict[str, list[str]]:
    """`search_full_name -> [player_id, ...]`, offense only."""
    index: dict[str, list[str]] = {}
    for player_id, player in players.items():
        if player.get("position") not in OFFENSE_POSITIONS:
            continue
        key = player.get("search_full_name") or normalize_name(
            f"{player.get('first_name', '')} {player.get('last_name', '')}"
        )
        index.setdefault(key, []).append(player_id)
    return index


def match_player(
    name: str, home_abbr: str, away_abbr: str, players: dict[str, dict], index: dict[str, list[str]]
) -> str | None:
    candidates = index.get(normalize_name(name), [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # Duplicate name (rare) -- the player must be on one of this game's
        # two teams, which is enough to break the tie.
        on_game = [pid for pid in candidates if players[pid].get("team") in (home_abbr, away_abbr)]
        if len(on_game) == 1:
            return on_game[0]
    return None


#: DK's own abbreviation prefix (first word of "NY Jets") is ambiguous for
#: the two NY teams and both LA teams -- Sleeper's `team` field uses the
#: full club code (NYJ/NYG/LAC/LAR), so those need the full name to resolve.
TEAM_ABBR_FIXES = {"NY Jets": "NYJ", "NY Giants": "NYG", "LA Chargers": "LAC", "LA Rams": "LAR"}


def team_abbr(full_name: str) -> str:
    return TEAM_ABBR_FIXES.get(full_name, full_name.split(" ", 1)[0])


def to_records(games: list[dict], players: dict[str, dict], index: dict[str, list[str]]) -> dict[str, dict]:
    """Flatten `games` into a `player_id`-keyed dict (or `dk:<slug>` when a
    name doesn't resolve, so an unmatched row is kept and visible rather than
    silently dropped).
    """
    records: dict[str, dict] = {}
    matched = 0
    for game in games:
        away_abbr, home_abbr = team_abbr(game["away"]), team_abbr(game["home"])
        for player in game["players"]:
            player_id = match_player(player["name"], home_abbr, away_abbr, players, index)
            team = players[player_id]["team"] if player_id else None
            opponent = away_abbr if team == home_abbr else home_abbr if team == away_abbr else None
            key = player_id or f"dk:{normalize_name(player['name'])}"
            matched += player_id is not None
            records[key] = {
                "dk_name": player["name"],
                "player_id": player_id,
                "team": team,
                "opponent": opponent,
                "matchup": f"{game['away']} at {game['home']}",
                "anytime": player["anytime"],
                "first": player["first"],
                "two_plus": player["two_plus"],
            }
    total = sum(len(g["players"]) for g in games)
    print(f"{matched}/{total} players matched to a Sleeper player_id")
    return records


def out_path(season: str, week: int) -> Path:
    return REPO_ROOT / "data" / "dk-odds" / season / f"wk{week}.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html_path")
    parser.add_argument("--season", required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    html = Path(args.html_path).read_text(encoding="utf-8", errors="ignore")
    games = parse_td_scorers(html)

    total_players = sum(len(g["players"]) for g in games)
    print(f"{len(games)} games, {total_players} player rows")
    if not games:
        sys.exit("No rows parsed -- DraftKings' markup may have changed, see the ponytail note in this script.")

    template = HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    fragment = template.replace("__DATA__", json.dumps({"games": games}, separators=(",", ":")))
    write_local(fragment, REPO_ROOT / "data" / "draftkings", "td-scorers")
    print("Wrote data/draftkings/td-scorers.html")

    players = fetch_players_nfl()
    records = to_records(games, players, build_index(players))
    path = out_path(args.season, args.week)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records))
    print(f"Saved {len(records)} player odds to {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
