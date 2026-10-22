"""Tier1: a user's page, GitHub-like -- their courses, images, courses using their tasks (user 2026-10-22)."""
import pytest

from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_course_web import pool as pool  # noqa: PLC0414  (fixture)


@pytest.fixture
def eve(pool: _Courses) -> _Courses:
    """Eve owns a public course and a private one; both use bob's task; bob also has a private image."""
    pool.call("POST", "/courses", "eve", {"name": "pub", "title": "Открытый курс Евы"})
    pool.call("POST", "/courses", "eve", {"name": "hush", "title": "Тайный курс Евы", "visibility": "private"})
    for course in ("eve/pub", "eve/hush"):
        pool.call("POST", f"/courses/{course}/tasks", "eve", {"repo": "bob/git-init", "tag": "1"})
    pool.push("bob/solo", "1", image="s")
    pool.call("PUT", "/revisions/bob/solo", "bob", {"visibility": "private"})
    pool.r.users.set_comment("bob", "ИТ-21 секрет")
    return pool


@pytest.mark.tier1
def test_a_users_page_shows_their_courses_images_and_where_their_tasks_are_used(eve: _Courses) -> None:
    status, html = _page(_browser(eve, "kid"), f"{eve.url}/u/bob")
    assert status == 200  # noqa: PLR2004
    assert "/c/bob/linux" in html and "/c/bob/closed" not in html        # own courses kid may see
    assert "bob/git-init" in html and "bob/solo" not in html              # own images kid may see
    assert "/c/eve/pub" in html and "/c/eve/hush" not in html             # courses using bob's task
    assert "секрет" not in html                                            # the comment is private


@pytest.mark.tier1
def test_who_may_see_a_private_course_sees_it_there(eve: _Courses) -> None:
    html = _page(_browser(eve, "eve"), f"{eve.url}/u/bob")[1]
    assert "/c/eve/hush" in html                                           # eve owns that course
    html = _page(_browser(eve, "bob"), f"{eve.url}/u/bob")[1]
    assert "bob/solo" in html and "/c/bob/closed" in html                 # bob sees his own
    assert "секрет" not in html


@pytest.mark.tier1
def test_an_unknown_user_is_404_and_search_links_to_the_page(eve: _Courses) -> None:
    assert _page(_browser(eve, "kid"), f"{eve.url}/u/nobody")[0] == 404  # noqa: PLR2004
    assert "href='/u/bob'" in _page(_browser(eve, "kid"), f"{eve.url}/search?q=bob&type=users")[1]
