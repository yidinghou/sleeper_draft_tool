"""Board · division/identity config — see
docs/spec/board/02-seat-identity-and-divisions.md.

No dedicated test file for the rest of config.py — it's pinned transitively
by every other suite (see docs/spec/league/guide.md). DIVISIONS/all_members/
division_index_for are new, standalone logic with nothing else exercising
them yet, so they get a direct one.
"""

from vorp.league.config import DIVISIONS, MY_USERNAME, all_members, division_index_for


def test_all_members_is_flat_and_covers_every_division():
    members = all_members()
    assert len(members) == sum(len(d.members) for d in DIVISIONS)
    assert set(members) == {m for d in DIVISIONS for m in d.members}


def test_all_members_has_no_duplicates():
    members = all_members()
    assert len(members) == len(set(m.lower() for m in members))


def test_my_username_is_a_real_division_member():
    # resolve_my_seat depends on MY_USERNAME actually being assigned
    # somewhere in DIVISIONS, or "my division" can never resolve.
    assert division_index_for(MY_USERNAME) is not None


def test_division_index_for_is_case_insensitive():
    member = DIVISIONS[0].members[0]
    assert division_index_for(member.upper()) == 0
    assert division_index_for(member.lower()) == 0


def test_division_index_for_unknown_username_is_none():
    assert division_index_for("nobody-in-this-league") is None


def test_division_index_for_blank_username_is_none():
    assert division_index_for(None) is None
    assert division_index_for("") is None
