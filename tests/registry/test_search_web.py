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


def _set_times(pool: _Courses, repo: str, *stamps: str) -> None:
    """Give `repo`'s versions of tag 1 these push moments (oldest first)."""
    import json  # noqa: PLC0415
    index = pool.r.store.root / ".repos" / repo / "repo.json"
    data = json.loads(index.read_text())
    for rev, at in zip(data["tags"]["1"]["revisions"], stamps, strict=False):
        rev["at"] = at
    index.write_text(json.dumps(data))


@pytest.mark.tier1
def test_tasks_show_their_last_push_newest_first_and_sort_by_publication(pool: _Courses) -> None:
    """User 2026-10-23: update date on tasks, recently pushed on top, a sort by publication date."""
    pool.push("bob/old", "1", image="o", task="to")
    pool.push("bob/old", "1", image="o2", task="to2")                   # published long ago, pushed today
    pool.push("bob/new", "1", image="n", task="tn")                     # published yesterday, once
    _set_times(pool, "bob/old", "2026-01-01T10:00:00Z", "2026-10-23T09:00:00Z")
    _set_times(pool, "bob/new", "2026-10-22T09:00:00Z")
    html = _page(_browser(pool, "eve"), f"{pool.url}/?type=tasks")[1]
    assert html.index("bob/old") < html.index("bob/new")                # the last push on top
    assert "data-pub='2026-01-01T10:00:00Z'" in html and "data-at='2026-10-23T09:00:00Z'" in html
    assert "обновлено" in html and "datetime='2026-10-23T09:00:00Z'" in html
    assert "value='-pub'" in html and "по дате публикации" in html


@pytest.mark.tier1
def test_the_client_searches_tasks_and_images_through_the_api(pool: _Courses) -> None:
    """The terminal searches the pool like the web (TODO 2026-10-23): what the caller may see."""
    from hashpass.registry.remote import RemoteRegistry  # noqa: PLC0415
    pool.push("bob/solo", "1", image="s")
    assert pool.call("PUT", "/revisions/bob/solo", "bob", {"visibility": "private"})[0] == 200  # noqa: PLR2004
    rows = RemoteRegistry(pool.url).repos("", token=pool.tok["eve"])
    names = {r["name"]: r for r in rows}
    assert "bob/git-init" in names and "bob/solo" not in names              # a private image stays hidden
    assert names["bob/git-init"]["task"] is True and names["bob/git-init"]["tags"][0]["ref"] == "bob/git-init:1_v1"
    assert [r["name"] for r in RemoteRegistry(pool.url).repos("solo", token=pool.tok["bob"])] == ["bob/solo"]
