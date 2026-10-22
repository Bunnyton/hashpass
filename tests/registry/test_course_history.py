"""Tier1: a course's people are visible; every change is in its history (spec 2026-10-23 §4)."""
import pytest

from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_course_web import pool as pool  # noqa: PLC0414  (fixture)


@pytest.mark.tier1
def test_the_owner_adds_people_by_login_and_everyone_sees_them(pool: _Courses) -> None:
    assert pool.call("PUT", "/courses/bob/linux/members/eve", "bob", {"role": "author"})[0] == 200  # noqa: PLR2004
    view = pool.call("GET", "/courses/bob/linux", "kid")[1]
    assert view["members"] == {"eve": "author"}
    html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")[1]
    assert "id='people'" in html and "/u/eve" in html and "/u/bob" in html
    owner = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")[1]
    assert "/members/__LOGIN__" in owner                                 # add by login


@pytest.mark.tier1
def test_every_change_lands_in_the_history_with_who_and_why(pool: _Courses) -> None:
    pool.push("bob/regex", "1", image="r", task="t")
    pool.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": "bob/regex", "tag": "1",
                                                          "comment": "нужно про регулярки"})
    pool.call("PUT", "/courses/bob/linux/members/eve", "bob", {"role": "maintainer"})
    history = pool.call("GET", "/courses/bob/linux", "kid")[1]["history"]
    assert [h["by"] for h in history[:2]] == ["bob", "bob"]               # newest first
    assert "eve" in history[0]["what"] and "сопровождающий" in history[0]["what"]
    assert "bob/regex:1" in history[1]["what"] and history[1]["comment"] == "нужно про регулярки"
    html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")[1]
    assert "id='history'" in html and "нужно про регулярки" in html
