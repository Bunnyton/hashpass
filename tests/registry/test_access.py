"""Tier1: the course permission matrix (spec 2026-10-21 §5, roles and boxes 2026-10-25 §3)."""
import pytest

from hashpass.registry import perms
from hashpass.registry.access import ACTIONS, can, course_perms
from hashpass.registry.courses import Course, set_member

#         peek view play propose add content people progress admins delete
_EXPECT = {
    ("public", None): "1100000000",          # anonymous
    ("public", "outsider"): "1111000000",
    ("public", "member"): "1111000000",
    ("public", "author"): "1111100000",
    ("public", "admin"): "1111111100",       # a course admin: the default boxes
    ("public", "keeper"): "1111000010",      # a course admin with `admins` only
    ("public", "owner"): "1111111111",
    ("private", None): "1000000000",
    ("private", "outsider"): "1000000000",
    ("private", "member"): "1111000000",     # members propose too (user 2026-10-25)
    ("private", "author"): "1111100000",
    ("private", "admin"): "1111111100",
    ("private", "keeper"): "1111000010",
    ("private", "owner"): "1111111111",
}


def _course(visibility: str) -> Course:
    return Course(id="c", owner="own", name="x", visibility=visibility,
                  members={"mem": "member", "aut": "author", "adm": "admin", "kee": "admin"},
                  perms={"kee": ["admins"]})


@pytest.mark.tier1
@pytest.mark.parametrize(("visibility", "who"), list(_EXPECT))
def test_matrix(visibility: str, who: str | None) -> None:
    user = {None: None, "outsider": "eve", "member": "mem", "author": "aut",
            "admin": "adm", "keeper": "kee", "owner": "own"}[who]
    got = "".join("1" if can(user, frozenset(), _course(visibility), a) else "0" for a in ACTIONS)
    assert got == _EXPECT[(visibility, who)]


@pytest.mark.tier1
def test_a_pool_admin_sees_a_private_course_it_is_not_in() -> None:
    course = _course("private")
    got = "".join("1" if can("root", frozenset({"progress"}), course, a) else "0" for a in ACTIONS)
    assert got == "1111000100"                       # its own box, nothing more
    assert all(can("root", perms.ALL, course, a) for a in ACTIONS)


@pytest.mark.tier1
def test_maintainer_reads_as_admin() -> None:
    course = Course.from_raw({"id": "c", "owner": "own", "name": "x", "members": {"old": "maintainer"}})
    assert course.role_of("old") == "admin"
    assert course_perms(course, "old") == perms.DEFAULT
    set_member(course, "new", "maintainer")           # an old client
    assert course.members["new"] == "admin"
    set_member(course, "new", "admin", ["people", "bogus"])
    assert course_perms(course, "new") == {"people"}
    set_member(course, "new", "author")
    assert "new" not in course.perms                    # no boxes left behind


@pytest.mark.tier1
def test_server_admin_may_do_everything() -> None:
    course = Course(id="c", owner="own", name="x", visibility="private")
    assert all(can("root", perms.ALL, course, a) for a in ACTIONS)


@pytest.mark.tier1
def test_unknown_action_is_a_bug() -> None:
    with pytest.raises(ValueError, match="unknown action"):
        can("a", frozenset(), Course(id="c", owner="o", name="x"), "fly")
