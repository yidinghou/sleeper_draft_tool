"""Board · seat identity and divisions -- see
docs/spec/board/02-seat-identity-and-divisions.md.

Covers random_fill, build_divisions, and resolve_my_seat directly.
seat_identity itself (the draft_order/picked_by join) is pinned in
test_sleeper_client.py; Board's wiring of all this into the payload is
pinned in test_draft_board.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "auction"))

from draft_board import build_divisions, random_fill, resolve_my_seat  # noqa: E402

from vorp.league.config import LEAGUE_CONFIG, MY_USERNAME  # noqa: E402


def test_random_fill_is_a_no_dup_deterministic_permutation():
    filled_a = random_fill({}, LEAGUE_CONFIG)
    filled_b = random_fill({}, LEAGUE_CONFIG)

    assert set(filled_a) == set(range(LEAGUE_CONFIG.teams))
    usernames = [v["username"] for v in filled_a.values()]
    assert len(usernames) == len(set(usernames))
    # Deterministic: same MOCK_SEED, same shuffle, every run.
    assert filled_a == filled_b


def test_random_fill_keeps_real_pins_exactly():
    pins = {5: {"user_id": "u1", "username": "alice", "display_name": "Alice"}}
    filled = random_fill(pins, LEAGUE_CONFIG)
    assert filled[5] == pins[5]
    # The pinned member doesn't also appear as a placeholder elsewhere.
    placeholders = [v["username"] for sid, v in filled.items() if sid != 5]
    assert "alice" not in [p.lower() for p in placeholders]


def test_build_divisions_orders_mine_first_and_permutes_seats():
    seat_users = random_fill({}, LEAGUE_CONFIG)
    my_seat = resolve_my_seat(seat_users, me_fallback=None)
    divisions, seat_order = build_divisions(seat_users, LEAGUE_CONFIG, my_seat)

    assert divisions[0]["mine"] is True
    assert all(not d["mine"] for d in divisions[1:])
    assert sorted(seat_order) == list(range(LEAGUE_CONFIG.teams))


def test_payload_auto_assigns_divisions_in_mock_mode():
    # No real pins at all -- every seat is a random_fill placeholder
    # (user_id is None), so build_divisions must fall back to the even
    # auto-split rather than pretending it has real division membership.
    seat_users = random_fill({}, LEAGUE_CONFIG)
    assert all(v["user_id"] is None for v in seat_users.values())

    my_seat = resolve_my_seat(seat_users, me_fallback=3)
    divisions, seat_order = build_divisions(seat_users, LEAGUE_CONFIG, my_seat)

    assert sum(len(d["seats"]) for d in divisions) == LEAGUE_CONFIG.teams
    assert not any(d["name"] == "Unassigned" for d in divisions)


def test_partial_identity_still_auto_assigns_divisions_but_infers_my_seat():
    pins = {2: {"user_id": "u1", "username": MY_USERNAME, "display_name": MY_USERNAME}}
    seat_users = random_fill(pins, LEAGUE_CONFIG)
    my_seat = resolve_my_seat(seat_users, me_fallback=None)
    assert my_seat == 2

    divisions, _ = build_divisions(seat_users, LEAGUE_CONFIG, my_seat)
    # Not fully seeded (only one real user_id) -> auto-split, but "my seat"
    # is still correctly inferred from the one resolved handle.
    assert sum(len(d["seats"]) for d in divisions) == LEAGUE_CONFIG.teams
    assert any(d["mine"] and 2 in d["seats"] for d in divisions)


def test_my_seat_is_inferred_from_the_configured_handle():
    seat_users = {
        0: {"user_id": "u1", "username": "someoneelse", "display_name": ""},
        1: {"user_id": "u2", "username": "", "display_name": MY_USERNAME.upper()},
    }
    assert resolve_my_seat(seat_users, me_fallback=None) == 1


def test_my_seat_falls_back_to_me_when_handle_absent():
    seat_users = {0: {"user_id": "u1", "username": "someoneelse", "display_name": ""}}
    assert resolve_my_seat(seat_users, me_fallback=5) == 4  # 1-indexed -> 0-indexed


def test_my_seat_ignores_a_placeholder_that_happens_to_share_the_handle():
    # MY_USERNAME is itself in all_members(), so random_fill can place it as
    # a *synthetic* placeholder (user_id None) on some seat. That must never
    # be read as "found my real seat" -- it's noise, not a Sleeper pin.
    seat_users = random_fill({}, LEAGUE_CONFIG)
    placeholder_seat = next(
        sid
        for sid, v in seat_users.items()
        if v["username"].lower() == MY_USERNAME.lower()
    )
    assert seat_users[placeholder_seat]["user_id"] is None
    assert resolve_my_seat(seat_users, me_fallback=7) == 6  # --me wins, not the placeholder
