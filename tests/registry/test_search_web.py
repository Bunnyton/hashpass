"""Tier1: one search page, GitHub-like -- users, courses, images on the left (user 2026-10-22)."""
import re

import pytest

from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_course_web import pool as pool  # noqa: PLC0414  (fixture)


def _tabs(html: str) -> dict[str, int]:
    return {name: int(n) for name, n in re.findall(r"data-tab='(\w+)'.*?<span class='count'>(\d+)</span>", html)}


@pytest.mark.tier1
def test_search_finds_courses_and_images_a_viewer_may_see(pool: _Courses) -> None:
    pool.push("bob/solo", "1", image="s")
    assert pool.call("PUT", "/revisions/bob/solo", "bob", {"visibility": "private"})[0] == 200  # noqa: PLR2004
    status, html = _page(_browser(pool, "eve"), f"{pool.url}/search?q=git")
    assert status == 200  # noqa: PLR2004
    assert _tabs(html) == {"users": 0, "courses": 0, "tasks": 1, "images": 0}   # a task apart from images
    assert "bob/git-init" in html and "версия 1" in html
    html = _page(_browser(pool, "eve"), f"{pool.url}/search?q=bob&type=courses")[1]
    assert "/c/bob/linux" in html and "/c/bob/closed" not in html  # a private course stays hidden
    html = _page(_browser(pool, "eve"), f"{pool.url}/search?q=solo&type=images")[1]
    assert "bob/solo" not in html                                   # a private image too
    assert "bob/solo" in _page(_browser(pool, "bob"), f"{pool.url}/search?q=solo&type=images")[1]


@pytest.mark.tier1
def test_users_are_found_by_login_and_their_private_comment_never_shows(pool: _Courses) -> None:
    # user 2026-10-22: «пускай будут видны пользователи, но не комментарии» -- the comment is
    # private: seen only while working with a course (its staff, the pool admin)
    pool.r.users.set_comment("kid", "ИТ-21 староста")
    for viewer in ("eve", "bunnyton"):
        html = _page(_browser(pool, viewer), f"{pool.url}/search?q=ki&type=users")[1]
        assert _tabs(html)["users"] == 1 and ">kid<" in html
        assert "староста" not in html
    html = _page(_browser(pool, "eve"), f"{pool.url}/search?q=%D0%98%D0%A2-21&type=users")[1]
    assert _tabs(html)["users"] == 0                       # a comment does not give a user away
