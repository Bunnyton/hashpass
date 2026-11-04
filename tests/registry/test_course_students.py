"""
Tier1: the course's staff invite students; a student is in only after accepting; a comment on joining.

User 2026-11-04: «отправить приглашение в курс, а стать участником можно только если принять это
приглашение… при принятии или присоединении — комментарий, который увидят авторы и админы курса».
"""
import json
from pathlib import Path

import pytest

from hashpass.registry.course_api import Enrollments
from tests.registry.test_course_api import _course, _Courses
from tests.registry.test_course_api import pool as pool  # noqa: PLC0414  (fixture)
from tests.registry.test_course_web import _browser, _page


def _enrolled(pool: _Courses) -> Enrollments:
    return Enrollments(Path(pool.r.store.root) / ".enrollments")


def _students(pool: _Courses) -> list[str]:
    cid = pool.call("GET", "/courses/bob/linux", "bob")[1]["id"]
    return [u for u in _enrolled(pool).users_of(cid) if u != "bob"]      # the owner is enrolled too


@pytest.mark.tier1
def test_an_invite_is_not_a_seat_until_it_is_accepted(pool: _Courses) -> None:
    path = _course(pool, "private")
    code, body = pool.call("POST", f"{path}/invites", "bob", {"users": "kid, max\nnobody"})
    assert code == 200, body  # noqa: PLR2004
    assert sorted(body["invited"]) == ["kid", "max"] and body["missing"] == ["nobody"] and "nobody" in body["message"]
    assert _students(pool) == []                                       # nobody is in yet
    seen = pool.call("GET", path, "kid")[1]
    assert "blocks" not in seen and seen["invited"]["by"] == "bob"      # the card says who invites
    assert [i["ref"] for i in pool.call("GET", "/courses", "kid")[1]["invites"]] == ["bob/linux"]
    code, _ = pool.call("POST", f"{path}/join", "kid", {"comment": "Иванов, ИУ7-31"})
    assert code == 200  # noqa: PLR2004
    assert _students(pool) == ["kid"] and "blocks" in pool.call("GET", path, "kid")[1]
    assert pool.call("GET", "/courses", "kid")[1]["invites"] == []
    assert [i["user"] for i in pool.call("GET", f"{path}/invites", "bob")[1]["invites"]] == ["max"]


@pytest.mark.tier1
def test_the_invitee_declines_and_the_team_revokes(pool: _Courses) -> None:
    path = _course(pool, "private")
    pool.call("POST", f"{path}/invites", "bob", {"users": ["kid", "max"]})
    assert pool.call("DELETE", f"{path}/invites/kid", "kid")[0] == 200            # declined  # noqa: PLR2004
    assert pool.call("DELETE", f"{path}/invites/max", "bob")[0] == 200            # revoked  # noqa: PLR2004
    assert pool.call("GET", f"{path}/invites", "bob")[1]["invites"] == []
    assert pool.call("POST", f"{path}/join", "kid", {})[0] == 403                 # no invite, no seat  # noqa: PLR2004


@pytest.mark.tier1
def test_only_who_manages_people_invites_and_nobody_else_drops_anothers_invite(pool: _Courses) -> None:
    path = _course(pool)
    assert pool.call("POST", f"{path}/invites", "kid", {"users": "max"})[0] == 403  # noqa: PLR2004
    pool.call("POST", f"{path}/invites", "bob", {"users": "max"})
    assert pool.call("DELETE", f"{path}/invites/max", "ann")[0] == 403  # noqa: PLR2004
    assert pool.call("POST", f"{path}/invites", "bob", {"users": "nobody"})[0] == 404  # noqa: PLR2004


@pytest.mark.tier1
def test_who_is_in_or_in_the_team_is_named_back_not_invited(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("PUT", f"{path}/members/max", "bob", {"role": "author"})
    pool.call("POST", f"{path}/join", "ann", {})
    pool.call("POST", f"{path}/invites", "bob", {"users": "kid"})
    body = pool.call("POST", f"{path}/invites", "bob", {"users": "max bob ann kid"})[1]
    assert sorted(body["team"]) == ["bob", "max"] and body["already"] == ["ann"] and body["pending"] == ["kid"]


@pytest.mark.tier1
def test_the_comment_on_joining_is_the_courses_and_the_staff_see_it(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("POST", f"{path}/join", "kid", {"comment": "Иванов И., ИУ7-31"})
    html = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    assert "Иванов И., ИУ7-31" in html[html.index("id='students'"):]
    pool.call("POST", f"{path}/join", "kid", {"comment": "Иванов Иван, ИУ7-32"})       # changed it
    assert "ИУ7-32" in _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    assert "ИУ7-32" not in _page(_browser(pool, "ann"), f"{pool.url}/c/bob/linux")[1]  # staff only


@pytest.mark.tier1
def test_removing_a_student_takes_the_course_away_but_keeps_the_progress(pool: _Courses) -> None:
    path = _course(pool, "private")
    pool.call("POST", f"{path}/invites", "bob", {"users": "kid"})
    pool.call("POST", f"{path}/join", "kid", {})
    code, body = pool.call("DELETE", f"{path}/students/kid", "bob")
    assert code == 200 and "kid" in body["message"]  # noqa: PLR2004
    assert _students(pool) == [] and "blocks" not in pool.call("GET", path, "kid")[1]


@pytest.mark.tier1
def test_users_are_found_by_a_part_of_the_login_and_only_logins_come_back(pool: _Courses) -> None:
    pool.r.users.add("anna.k", "pw-correct1", role="student", comment="секрет")
    code, body = pool.call("GET", "/users?q=an", "bob")
    assert code == 200 and body["users"][:2] == ["ann", "anna.k"]  # noqa: PLR2004  (prefix first)
    assert "секрет" not in json.dumps(body, ensure_ascii=False)
    assert pool.call("GET", "/users?q=an", None)[0] in (401, 403)  # signed in only


@pytest.mark.tier1
def test_the_students_tab_has_the_invite_link_the_search_and_who_waits(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("POST", f"{path}/invites", "bob", {"users": "max"})
    invite = pool.call("GET", path, "bob")[1]["invite"]
    html = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    tab = html[html.index("id='students'"):]
    assert f"invite={invite}" in tab and "POST /courses/bob/linux/invites" in tab and "data-user-search" in tab
    assert "DELETE /courses/bob/linux/invites/max" in tab
    kid = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")[1]
    assert "POST /courses/bob/linux/invites" not in kid


@pytest.mark.tier1
def test_the_invitee_accepts_on_the_course_page_with_a_comment(pool: _Courses) -> None:
    path = _course(pool, "private")
    pool.call("POST", f"{path}/invites", "bob", {"users": "kid"})
    html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")[1]
    assert "POST /courses/bob/linux/join" in html and "name='comment'" in html and "bob" in html
    assert "DELETE /courses/bob/linux/invites/kid" in html                                 # decline
    mine = _page(_browser(pool, "kid"), f"{pool.url}/c")[1]
    assert "/c/bob/linux" in mine and "Принять" in mine
