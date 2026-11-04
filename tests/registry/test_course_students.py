"""
Tier1: the course's staff add students by login and remove them; the invite link sits right there.

User 2026-11-04: «Хочу добавлять пользователей в курс — ссылка приглашения и вручную приглашать».
"""
from pathlib import Path

import pytest

from hashpass.registry.course_api import Enrollments
from tests.registry.test_course_api import _course, _Courses
from tests.registry.test_course_api import pool as pool  # noqa: PLC0414  (fixture)
from tests.registry.test_course_web import _browser, _page


def _enrolled(pool: _Courses) -> Enrollments:
    return Enrollments(Path(pool.r.store.root) / ".enrollments")


def _students(pool: _Courses, cid: str) -> list[str]:
    return [u for u in _enrolled(pool).users_of(cid) if u != "bob"]      # the owner is enrolled too


def _course_id(pool: _Courses) -> str:
    return pool.call("GET", "/courses/bob/linux", "bob")[1]["id"]


@pytest.mark.tier1
def test_staff_add_several_logins_at_once_and_hear_who_was_not_found(pool: _Courses) -> None:
    path = _course(pool, "private")
    code, body = pool.call("POST", f"{path}/students", "bob", {"users": "kid, max\nnobody  ann"})
    assert code == 200, body  # noqa: PLR2004
    assert "kid" in body["message"] and "nobody" in body["message"]
    assert sorted(body["added"]) == ["ann", "kid", "max"] and body["missing"] == ["nobody"]
    cid = _course_id(pool)
    assert _students(pool, cid) == ["ann", "kid", "max"]
    assert "blocks" in pool.call("GET", path, "kid")[1]      # a private course opens for them
    assert pool.call("POST", f"{path}/students", "bob", {"users": "kid"})[1]["already"] == ["kid"]


@pytest.mark.tier1
def test_only_who_manages_people_adds_or_removes(pool: _Courses) -> None:
    path = _course(pool)
    assert pool.call("POST", f"{path}/students", "kid", {"users": "max"})[0] == 403  # noqa: PLR2004
    assert pool.call("DELETE", f"{path}/students/max", "kid")[0] == 403  # noqa: PLR2004
    assert pool.call("POST", f"{path}/students", "bob", {"users": "nobody"})[0] == 404  # noqa: PLR2004


@pytest.mark.tier1
def test_the_team_is_not_turned_into_students(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("PUT", f"{path}/members/max", "bob", {"role": "author"})
    body = pool.call("POST", f"{path}/students", "bob", {"users": "max bob"})[1]
    assert sorted(body["team"]) == ["bob", "max"] and body["added"] == []
    assert pool.call("GET", path, "bob")[1]["members"]["max"] == "author"


@pytest.mark.tier1
def test_removing_a_student_takes_the_course_away_but_keeps_the_progress(pool: _Courses) -> None:
    path = _course(pool, "private")
    pool.call("POST", f"{path}/students", "bob", {"users": "kid"})
    code, body = pool.call("DELETE", f"{path}/students/kid", "bob")
    assert code == 200 and "kid" in body["message"]  # noqa: PLR2004
    assert _students(pool, _course_id(pool)) == []
    assert "kid" not in pool.call("GET", path, "bob")[1].get("members", {})
    assert "blocks" not in pool.call("GET", path, "kid")[1]  # closed again: only its card


@pytest.mark.tier1
def test_the_students_tab_offers_the_invite_link_and_the_add_form_to_staff_only(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("POST", f"{path}/students", "bob", {"users": "kid"})
    invite = pool.call("GET", path, "bob")[1]["invite"]
    html = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    students = html[html.index("id='students'"):]
    assert f"invite={invite}" in students and "POST /courses/bob/linux/students" in students
    assert "DELETE /courses/bob/linux/students/kid" in students
    assert "POST /courses/bob/linux/students" not in _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")[1]
