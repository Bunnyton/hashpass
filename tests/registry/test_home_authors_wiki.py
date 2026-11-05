"""
Tier1: the home page shows the top authors and the wikis.

User 2026-11-05: «добавь топ авторов на главной странице и wiki».
"""
import pytest

from hashpass.registry.progress_store import ProgressStore
from hashpass.registry.wiki_store import pack
from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_course_web import pool as pool  # noqa: PLC0414  (fixture)
from tests.registry.test_push_commit import _http


@pytest.mark.tier1
def test_the_home_page_ranks_authors_by_what_others_solved(pool: _Courses) -> None:
    pool.push("eve/regex", "1", image="r", task="tr", user="eve")
    progress = ProgressStore(pool.r.store.root / "progress")
    for who in ("kid", "max", "ann"):
        progress.record(who, "bob/git-init:1", status="passed", ts="t")
    progress.record("kid", "eve/regex:1", status="passed", ts="t")
    html = _page(_browser(pool, "kid"), f"{pool.url}/")[1]
    top = html[html.index("Топ авторов"):]
    assert top.index("bob") < top.index("eve")                      # 3 solves beat 1
    assert "решили 3 раза" in top or "3 решения" in top


@pytest.mark.tier1
def test_the_home_page_shows_wikis_and_the_wiki_tab_lists_them_all(pool: _Courses) -> None:
    _http("POST", f"{pool.url}/wiki/bob/git-init?base=0", token=pool.tok["bob"],
          data=pack({"wiki.md": "---\ntags: git\n---\n# Теория git\n\nЗачем нужен git.\n".encode()}))
    html = _page(_browser(pool, "kid"), f"{pool.url}/")[1]
    assert "Теория git" in html and "href='/web/wiki/bob/git-init/wiki.md'" in html
    tab = _page(_browser(pool, "kid"), f"{pool.url}/?type=wiki")[1]
    assert "Теория git" in tab                                      # no query: every wiki
    assert "Теория git" not in _page(_browser(pool, None), f"{pool.url}/")[1]   # signed in only
