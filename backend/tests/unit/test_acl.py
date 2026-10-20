"""The pure ACL decision function: who may read which collection."""

from __future__ import annotations

import itertools
import uuid

from app.services.acl import CollectionAccessRow, resolve_allowed

WS_A, WS_B = uuid.uuid4(), uuid.uuid4()
HR, FINANCE = uuid.uuid4(), uuid.uuid4()
OPEN_A, HR_ONLY_A, MIXED_A, OPEN_B = (uuid.uuid4() for _ in range(4))

ROWS = [
    CollectionAccessRow(OPEN_A, WS_A, "workspace", frozenset()),
    CollectionAccessRow(HR_ONLY_A, WS_A, "groups", frozenset({HR})),
    CollectionAccessRow(MIXED_A, WS_A, "groups", frozenset({HR, FINANCE})),
    CollectionAccessRow(OPEN_B, WS_B, "workspace", frozenset()),
]


def allowed(memberships: dict[uuid.UUID, str], groups: set[uuid.UUID]) -> set[uuid.UUID]:
    return set(resolve_allowed(memberships, groups, ROWS))


def test_plain_member_sees_only_workspace_collections() -> None:
    assert allowed({WS_A: "member"}, set()) == {OPEN_A}


def test_group_member_also_sees_their_group_collections() -> None:
    assert allowed({WS_A: "member"}, {HR}) == {OPEN_A, HR_ONLY_A, MIXED_A}
    assert allowed({WS_A: "member"}, {FINANCE}) == {OPEN_A, MIXED_A}


def test_admin_sees_every_collection_in_their_workspace_only() -> None:
    assert allowed({WS_A: "admin"}, set()) == {OPEN_A, HR_ONLY_A, MIXED_A}


def test_non_members_see_nothing() -> None:
    assert allowed({}, {HR}) == set()


def test_membership_in_one_workspace_never_grants_another() -> None:
    assert allowed({WS_B: "admin"}, {HR}) == {OPEN_B}
    assert allowed({WS_A: "member", WS_B: "member"}, set()) == {OPEN_A, OPEN_B}


def test_a_group_id_alone_is_not_enough_without_membership() -> None:
    assert HR_ONLY_A not in allowed({WS_B: "member"}, {HR})


def test_exhaustive_truth_table() -> None:
    """Every combination of role, group membership and collection kind."""
    for role, in_hr, in_finance in itertools.product(["admin", "member"], [False, True], [False, True]):
        groups = {g for g, flag in ((HR, in_hr), (FINANCE, in_finance)) if flag}
        got = allowed({WS_A: role}, groups)
        assert OPEN_A in got
        assert (HR_ONLY_A in got) == (role == "admin" or in_hr)
        assert (MIXED_A in got) == (role == "admin" or in_hr or in_finance)
        assert OPEN_B not in got


def test_result_has_no_duplicates_and_preserves_input_order() -> None:
    result = resolve_allowed({WS_A: "admin"}, set(), ROWS)
    assert result == [OPEN_A, HR_ONLY_A, MIXED_A]
