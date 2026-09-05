"""Board · sleeper_client — see docs/spec/board/01-live-data-ingestion.md.

Mirrors src/sleeper.test.ts's coverage for the ported functions, plus
seat_identity, which has no TypeScript counterpart.
"""

from vorp.sleeper_client import (
    cache_busted_url,
    draft_fingerprint,
    parse_nomination,
    seat_identity,
    sleeper_player_full_name,
)


def test_cache_busted_url_appends_timestamp_query_param():
    url = cache_busted_url("/draft/123", now=lambda: 1724454000123)
    assert url == "https://api.sleeper.app/v1/draft/123?_cb=1724454000123"


def test_cache_busted_url_appends_with_ampersand_when_query_string_present():
    url = cache_busted_url("/league/1/users?foo=bar", now=lambda: 42)
    assert url == "https://api.sleeper.app/v1/league/1/users?foo=bar&_cb=42"


def _draft(**metadata):
    return {
        "draft_id": "d1",
        "league_id": "l1",
        "season": "2026",
        "type": "auction",
        "status": "in_progress",
        "settings": {},
        "draft_order": None,
        "metadata": metadata,
    }


def test_draft_fingerprint_changes_when_nominated_player_changes():
    base = _draft(nominated_player_id="100", highest_offer="10", offering_slot="2")
    changed = _draft(nominated_player_id="200", highest_offer="10", offering_slot="2")
    assert draft_fingerprint(base) != draft_fingerprint(changed)


def test_draft_fingerprint_stable_when_nothing_relevant_changes():
    draft = _draft(nominated_player_id="100", highest_offer="10", offering_slot="2")
    assert draft_fingerprint(draft) == draft_fingerprint(dict(draft))


def test_parse_nomination_reports_none_when_board_is_empty():
    nomination = parse_nomination(_draft())
    assert nomination.player_id is None
    assert nomination.highest_offer is None


def test_parse_nomination_extracts_high_bid_and_offering_seat():
    draft = _draft(
        nominated_player_id="4623",
        nominating_slot="1",
        highest_offer="42",
        offering_slot="5",
    )
    nomination = parse_nomination(draft)
    assert nomination.player_id == "4623"
    assert nomination.nominating_slot == 1
    assert nomination.highest_offer == 42
    assert nomination.offering_slot == 5


def test_sleeper_player_full_name_prefers_full_name():
    name = sleeper_player_full_name(
        {"first_name": "Patrick", "last_name": "Mahomes", "full_name": "Patrick Mahomes"}
    )
    assert name == "Patrick Mahomes"


def test_sleeper_player_full_name_falls_back_to_first_plus_last():
    name = sleeper_player_full_name({"first_name": "Patrick", "last_name": "Mahomes"})
    assert name == "Patrick Mahomes"


USERS = [
    {"user_id": "u1", "username": "alice", "display_name": "Alice"},
    {"user_id": "u2", "username": "bob", "display_name": "Bob"},
]


def test_seat_identity_from_dict_shaped_draft_order():
    draft = {"draft_order": {"u1": 3, "u2": 7}}
    identity = seat_identity(draft, USERS)
    assert identity[3] == {"user_id": "u1", "username": "alice", "display_name": "Alice"}
    assert identity[7]["display_name"] == "Bob"


def test_seat_identity_from_array_shaped_draft_order():
    # index 0 -> slot 1, a None entry is an unseeded slot.
    draft = {"draft_order": ["u1", None, "u2"]}
    identity = seat_identity(draft, USERS)
    assert identity[1]["user_id"] == "u1"
    assert 2 not in identity
    assert identity[3]["user_id"] == "u2"


def test_seat_identity_falls_back_to_picks_for_unseeded_slots():
    draft = {"draft_order": {"u1": 3}}
    picks = [{"draft_slot": 7, "picked_by": "u2"}]
    identity = seat_identity(draft, USERS, raw_picks=picks)
    assert identity[3]["user_id"] == "u1"
    assert identity[7]["user_id"] == "u2"


def test_seat_identity_picks_never_override_draft_order():
    draft = {"draft_order": {"u1": 3}}
    picks = [{"draft_slot": 3, "picked_by": "u2"}]
    identity = seat_identity(draft, USERS, raw_picks=picks)
    assert identity[3]["user_id"] == "u1"
