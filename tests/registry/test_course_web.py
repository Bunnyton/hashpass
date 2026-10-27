"""Tier1: course pages render what the viewer may see (spec 2026-10-21 §11)."""
import http.cookiejar
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from hashpass.registry import era
from tests.registry.test_course_api import _Courses


def _browser(pool: _Courses, user: str | None) -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    if user:
        data = urllib.parse.urlencode({"user": user, "password": "pw-correct1"}).encode()
        opener.open(urllib.request.Request(f"{pool.url}/web/login", data=data), timeout=10)  # noqa: S310
    return opener


def _page(opener: urllib.request.OpenerDirector, url: str) -> tuple[int, str]:
    try:
        with opener.open(url, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/git-init", "1", image="one", task="t1")
    p.call("POST", "/courses", "bob", {"name": "linux", "title": "Linux для всех"})
    p.call("POST", "/courses", "bob", {"name": "closed", "title": "Секретный", "visibility": "private"})
    block = p.call("POST", "/courses/bob/linux/blocks", "bob", {"name": "Git"})[1]["id"]
    p.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": "bob/git-init", "tag": "1", "block_id": block})
    return p


@pytest.mark.tier1
def test_any_user_signs_in_and_finds_courses_on_the_home_page(pool: _Courses) -> None:
    status, html = _page(_browser(pool, "kid"), f"{pool.url}/?type=courses")
    assert status == 200  # noqa: PLR2004
    assert "Linux для всех" in html
    assert "Секретный" not in html                       # a private course is not listed
    assert ">Прогресс<" not in html                       # staff pages stay off a student's nav
    assert ">Главная<" in html and ">Мои курсы<" in html


@pytest.mark.tier1
def test_course_page_for_a_student_and_for_the_owner(pool: _Courses) -> None:
    status, html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")
    assert status == 200  # noqa: PLR2004
    assert "bob/git-init:1_v1" in html and "Пройти курс" in html
    assert "id='settings-tab'" not in html and "data-layout-url" not in html
    assert "id='people'" in html                                          # everyone sees who is in
    owner = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    assert "data-layout-url='/courses/bob/linux/layout'" in owner
    assert "id='settings-tab'" in owner and "/members/__LOGIN__" in owner


@pytest.mark.tier1
def test_private_course_shows_only_the_request_form(pool: _Courses) -> None:
    html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/closed")[1]
    assert "Запросить доступ" in html
    assert "Задания" not in html
    invite = pool.call("GET", "/courses/bob/closed", "bob")[1]["invite"]
    html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/closed?invite={invite}")[1]
    assert "Вступить по приглашению" in html


@pytest.mark.tier1
def test_login_returns_to_the_invite_link(pool: _Courses) -> None:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    target = "/c/bob/closed?invite=abc"
    data = urllib.parse.urlencode({"user": "kid", "password": "pw-correct1", "next": target}).encode()
    with opener.open(urllib.request.Request(f"{pool.url}/web/login", data=data), timeout=10) as resp:  # noqa: S310
        assert resp.url.endswith(target)
    data = urllib.parse.urlencode({"user": "kid", "password": "pw-correct1",
                                   "next": "https://evil.example/"}).encode()
    with opener.open(urllib.request.Request(f"{pool.url}/web/login", data=data), timeout=10) as resp:  # noqa: S310
        assert resp.url.endswith("/u/kid")                  # never off-site: home is one's own page


@pytest.mark.tier1
def test_course_pages_are_off_without_the_switch(pool: _Courses, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(era, "COURSES", False)
    assert _page(_browser(pool, None), f"{pool.url}/c")[0] == 404  # noqa: PLR2004


@pytest.mark.tier1
def test_image_card_for_its_owner_and_for_others(pool: _Courses) -> None:
    owner = _page(_browser(pool, "bob"), f"{pool.url}/web/image/bob/git-init:1")[1]
    # user 2026-10-23: «не вкладками, а как на github» -- one page, the versions a page of their own
    assert "data-tab" not in owner and "class='repo-grid'" in owner
    assert "href='/web/versions/bob/git-init'" in owner
    for cmd in ("hashpass run bob/git-init:1", "hashpass pull bob/git-init:1", "hashpass clone bob/git-init:1"):
        assert cmd in owner
    assert "hpcopy(this)" in owner
    versions = _page(_browser(pool, "bob"), f"{pool.url}/web/versions/bob/git-init")[1]
    assert "id='revisions'" in versions and "1_v1" in versions and "версия 1" in versions
    # user 2026-10-22: «не ревизия, а версия» (the `_vN` tag stays under the hood, shown as a
    # version beside the tag); «файлы и исходники одно и то же» -- one sources box
    assert "версия 1" in owner and "Версии" in owner
    assert "евизи" not in owner
    assert "<h2>Файлы</h2>" not in owner and "Прикрепить" not in owner
    assert "href='/web/settings/bob/git-init'" in owner                   # settings: a page of their own
    assert "data-api='PUT /revisions/bob/git-init'" in _page(_browser(pool, "bob"), f"{pool.url}/web/settings/bob/git-init")[1]
    assert "Используется в" in owner and "/c/bob/linux" in owner
    other = _page(_browser(pool, "eve"), f"{pool.url}/web/image/bob/git-init:1")[1]
    assert "Форкнуть" in other
    assert "/web/settings/" not in other
    pool.push("bob/solo", "1", image="s")
    assert pool.call("PUT", "/revisions/bob/solo", "bob", {"visibility": "private"})[0] == 200  # noqa: PLR2004
    assert _page(_browser(pool, "eve"), f"{pool.url}/web/image/bob/solo:1")[0] == 404  # noqa: PLR2004


@pytest.mark.tier1
def test_admin_users_page_searches_and_lists_deletion_requests(pool: _Courses) -> None:
    pool.r.users.set_comment("kid", "ИТ-21 староста")
    pool.push("eve/regex", "1", image="r", task="t", user="eve")
    pool.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": "eve/regex", "tag": "1"})
    assert pool.call("DELETE", "/revisions/eve/regex/1/1", "eve")[0] == 202  # noqa: PLR2004
    html = _page(_browser(pool, "bunnyton"), f"{pool.url}/web/users?q=%D0%98%D0%A2-21")[1]
    assert ">kid<" in html and ">max<" not in html
    assert "Запросы на удаление версий" in html and "eve/regex:1" in html and "версия 1" in html
    assert "евизи" not in html


@pytest.mark.tier1
def test_staff_are_not_listed_as_students(pool: _Courses) -> None:
    pool.call("POST", "/courses/bob/linux/join", "kid", {})
    html = _page(_browser(pool, "bunnyton"), f"{pool.url}/c/bob/linux")[1]
    students = html.split("id='students'", 1)[1].split("</table>", 1)[0]
    assert ">kid<" in students and ">bob<" not in students


@pytest.mark.tier1
def test_the_course_owner_sees_its_students(pool: _Courses) -> None:
    """
    Spec 2026-10-25 §3-§4: who takes a course -- its owner, its admins with `progress`, a pool admin.

    (ed39fb6 had the pool admin alone: nobody was an admin in a course then.)
    """
    pool.call("POST", "/courses/bob/linux/join", "kid", {})
    owner = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    assert "id='students'" in owner and ">kid<" in owner.split("id='students'", 1)[1]
    assert _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux/u/kid")[0] == 200  # noqa: PLR2004
    pool.r.users.set_role("bob", "user")                           # no pool rights: the course's own
    seen = pool.call("GET", "/progress", "bob")[1]["progress"]
    assert set(seen) == {"bob", "kid"}
    assert _page(_browser(pool, "bob"), f"{pool.url}/web/history?user=kid&ref=bob/git-init:1")[0] == 200  # noqa: PLR2004


@pytest.mark.tier1
@pytest.mark.parametrize(("role", "boxes"), [("admin", ["content", "people"]), ("author", None)])
def test_a_course_admin_without_progress_or_an_author_does_not(pool: _Courses, role: str,
                                                                boxes: list[str] | None) -> None:
    pool.call("POST", "/courses/bob/linux/join", "kid", {})
    body = {"role": role} | ({"perms": boxes} if boxes is not None else {})
    assert pool.call("PUT", "/courses/bob/linux/members/eve", "bob", body)[0] == 200  # noqa: PLR2004
    page = _page(_browser(pool, "eve"), f"{pool.url}/c/bob/linux")[1]
    assert "id='students'" not in page
    assert _page(_browser(pool, "eve"), f"{pool.url}/c/bob/linux/u/kid")[0] == 403  # noqa: PLR2004
    assert set(pool.call("GET", "/progress", "eve")[1]["progress"]) == {"eve"}
    assert pool.call("GET", "/solution/bob/git-init:1?user=kid", "eve")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_a_pool_admin_without_progress_does_not(pool: _Courses) -> None:
    pool.call("POST", "/courses/bob/linux/join", "kid", {})
    pool.r.users.add("clerk", "pw-correct1", role="admin")
    pool.r.users.set_perms("clerk", ["people", "content"])
    page = _page(_browser(pool, "clerk"), f"{pool.url}/c/bob/linux")[1]
    assert "id='students'" not in page
    assert _page(_browser(pool, "clerk"), f"{pool.url}/c/bob/linux/u/kid")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_only_the_owner_sees_the_address_field(pool: _Courses) -> None:
    owner = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    assert "name='name' value='linux'" in owner and "data-then='go:/c/{ref}'" in owner
    pool.call("PUT", "/courses/bob/linux/members/max", "bob", {"role": "admin", "perms": ["content"]})
    admin = _page(_browser(pool, "max"), f"{pool.url}/c/bob/linux")[1]
    assert "id='settings-tab'" in admin and "name='name' value='linux'" not in admin
    pool.call("PUT", "/courses/bob/linux", "bob", {"name": "base"})
    assert _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")[0] == 404  # noqa: PLR2004
    assert "Linux для всех" in _page(_browser(pool, "kid"), f"{pool.url}/c/bob/base")[1]
