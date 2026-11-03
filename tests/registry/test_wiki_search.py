"""Tier1: the site's search finds wiki pages -- by their text and by the author's tags."""
from urllib.parse import quote

import pytest

from hashpass.registry.wiki_store import pack
from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_course_web import pool as pool  # noqa: PLC0414  (fixture)
from tests.registry.test_push_commit import _http

MAIN = "---\ntags: regex, grep\n---\n# Регулярки\n\nВступление.\n"
MORE = "# Повторы\n\n" + "текст " * 50 + "Квантификатор `+` значит «один или больше».\n"


def _wiki(pool: _Courses, repo: str) -> None:
    code, _ = _http("POST", f"{pool.url}/wiki/{repo}?base=0", token=pool.tok["bob"],
                    data=pack({"wiki.md": MAIN.encode(), "wiki/repeat.md": MORE.encode()}))
    assert code == 200  # noqa: PLR2004


@pytest.mark.tier1
def test_a_word_of_a_page_finds_that_page_with_a_snippet(pool: _Courses) -> None:
    _wiki(pool, "bob/git-init")
    html = _page(_browser(pool, "eve"), f"{pool.url}/?q={quote('квантификатор')}&type=wiki")[1]
    assert "/web/wiki/bob/git-init/wiki/repeat.md" in html and "Повторы" in html
    assert "один или больше" in html
    assert "data-tab='wiki'" in html


@pytest.mark.tier1
def test_a_hash_finds_by_tag_exactly(pool: _Courses) -> None:
    _wiki(pool, "bob/git-init")
    html = _page(_browser(pool, "eve"), f"{pool.url}/?q=%23regex&type=wiki")[1]
    assert "/web/wiki/bob/git-init/wiki.md" in html and "#grep" in html
    assert "/web/wiki/bob/git-init" not in _page(_browser(pool, "eve"), f"{pool.url}/?q=%23reg&type=wiki")[1]


@pytest.mark.tier1
def test_a_private_task_keeps_its_wiki_out_of_others_search(pool: _Courses) -> None:
    pool.push("bob/solo", "1", image="s")
    _wiki(pool, "bob/solo")
    assert pool.call("PUT", "/revisions/bob/solo", "bob", {"visibility": "private"})[0] == 200  # noqa: PLR2004
    assert "/web/wiki/bob/solo" not in _page(_browser(pool, "eve"), f"{pool.url}/?q=%23regex&type=wiki")[1]
    assert "/web/wiki/bob/solo" in _page(_browser(pool, "bob"), f"{pool.url}/?q=%23regex&type=wiki")[1]
    assert "/web/wiki/" not in _page(_browser(pool, None), f"{pool.url}/?q=%23regex&type=wiki")[1]
