"""Tier1: course admins and their boxes; who sends a task into a course (spec 2026-10-25 §3)."""
import pytest

from tests.registry.test_course_api import _course, _Courses
from tests.registry.test_course_api import pool as pool  # noqa: PLC0414  (the fixture)

_OK, _CREATED, _FORBIDDEN = 200, 201, 403


def _members(pool: _Courses) -> dict:
    return pool.call("GET", "/courses/bob/linux", "bob")[1]


@pytest.mark.tier1
def test_only_admins_box_makes_a_course_admin(pool: _Courses) -> None:
    path = _course(pool)
    assert pool.call("PUT", f"{path}/members/ann", "bob", {"role": "admin"})[0] == _OK
    # ann is a course admin with the default boxes: people, but not `admins`
    assert pool.call("PUT", f"{path}/members/kid", "ann", {"role": "author"})[0] == _OK
    assert pool.call("PUT", f"{path}/members/kid", "ann", {"role": "admin"})[0] == _FORBIDDEN
    assert pool.call("PUT", f"{path}/members/ann", "bob",
                     {"role": "admin", "perms": ["admins", "people"]})[0] == _OK
    assert _members(pool)["perms"]["ann"] == ["admins", "people"]
    assert pool.call("PUT", f"{path}/members/kid", "ann",
                     {"role": "admin", "perms": ["people"]})[0] == _OK
    assert _members(pool)["perms"]["kid"] == ["people"]


@pytest.mark.tier1
def test_a_box_one_lacks_cannot_be_given(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("PUT", f"{path}/members/ann", "bob", {"role": "admin", "perms": ["admins", "content"]})
    code, body = pool.call("PUT", f"{path}/members/kid", "ann", {"role": "admin", "perms": ["progress"]})
    assert code == _FORBIDDEN and "прав" in body["error"]
    # taking an admin away is the `admins` box too: ann (no `people`) still may
    pool.call("PUT", f"{path}/members/max", "bob", {"role": "admin"})
    assert pool.call("PUT", f"{path}/members/max", "ann", {"role": "member"})[0] == _OK


@pytest.mark.tier1
def test_nobody_changes_own_role(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("PUT", f"{path}/members/ann", "bob", {"role": "admin", "perms": ["admins", "people"]})
    assert pool.call("PUT", f"{path}/members/ann", "ann", {"role": "admin", "perms": ["admins", "people", "content"]})[0] == _FORBIDDEN
    assert pool.call("DELETE", f"{path}/members/ann", "ann")[0] == _FORBIDDEN


@pytest.mark.tier1
def test_old_clients_send_maintainer(pool: _Courses) -> None:
    path = _course(pool)
    assert pool.call("PUT", f"{path}/members/ann", "bob", {"role": "maintainer"})[0] == _OK
    view = _members(pool)
    assert view["members"]["ann"] == "admin"
    assert view["perms"]["ann"] == ["content", "people", "progress"]


@pytest.mark.tier1
def test_a_private_member_proposes_an_outsider_cannot(pool: _Courses) -> None:
    path = _course(pool, "private")
    pool.call("POST", f"{path}/blocks", "bob", {"name": "B"})
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})
    pool.call("PUT", f"{path}/members/eve", "bob", {"role": "author"})
    code, body = pool.call("POST", f"{path}/tasks", "kid", {"repo": "bob/git-init", "tag": "1"})
    assert (code, "proposal" in body) == (_CREATED, True)
    assert pool.call("POST", f"{path}/tasks", "max", {"repo": "bob/git-init", "tag": "1"})[0] == _FORBIDDEN
    code, body = pool.call("POST", f"{path}/tasks", "eve", {"repo": "eve/regex", "tag": "1"})
    assert (code, "task" in body) == (_CREATED, True)


@pytest.mark.tier1
def test_the_people_tab_shows_boxes_to_the_admins_box_only(pool: _Courses) -> None:
    from tests.registry.test_course_web import _browser, _page  # noqa: PLC0415
    path = _course(pool)
    pool.call("PUT", f"{path}/members/ann", "bob", {"role": "admin"})
    pool.call("PUT", f"{path}/members/max", "bob", {"role": "admin"})
    owner = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    assert owner.count("name='perms'") == 8  # noqa: PLR2004                     # four boxes for each of two admins
    ann = _page(_browser(pool, "ann"), f"{pool.url}/c/bob/linux")[1]
    assert "name='perms'" not in ann and "Люди и доступ" in ann  # ann sees max's boxes, cannot set
    assert "<option value='admin'>" not in ann
