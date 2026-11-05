"""Tier1: a task's wiki on the pool -- read like the task card, edited in the browser, versions aside."""
import urllib.error
import urllib.parse
import urllib.request

import pytest

from hashpass.registry.wiki_store import pack, unpack
from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_course_web import pool as pool  # noqa: PLC0414  (fixture)
from tests.registry.test_push_commit import _http

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
MAIN = "---\ntags: git, init\n---\n# Как завести репозиторий\n\nКоманда `git init` создаёт `.git`.\n"


def _push(pool: _Courses, files: dict[str, bytes], base: int = 0, user: str = "bob",
          repo: str = "bob/git-init") -> tuple[int, dict]:
    return _http("POST", f"{pool.url}/wiki/{repo}?base={base}&message=m", token=pool.tok[user], data=pack(files))


def _raw(opener: urllib.request.OpenerDirector, url: str, data: dict | None = None) -> tuple[int, bytes, dict]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with opener.open(urllib.request.Request(url, data=body), timeout=10) as resp:  # noqa: S310  (http to the test pool)
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


@pytest.mark.tier1
def test_the_owner_pushes_a_wiki_and_a_reader_sees_it_with_tags(pool: _Courses) -> None:
    assert _push(pool, {"wiki.md": MAIN.encode(), "wiki/more.md": b"# More\n"}) == (200, {"n": 1, "changed": ["wiki.md", "wiki/more.md"]})
    req = urllib.request.Request(f"{pool.url}/wiki/bob/git-init", headers={"Authorization": f"Bearer {pool.tok['eve']}"})  # noqa: S310  (http to the test pool)
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        assert resp.headers["X-Wiki-Version"] == "1" and unpack(resp.read())["wiki/more.md"] == b"# More\n"
    status, html = _page(_browser(pool, "eve"), f"{pool.url}/web/wiki/bob/git-init")
    assert status == 200 and "Как завести репозиторий" in html and "<code>git init</code>" in html  # noqa: PLR2004
    assert "/?q=%23git&amp;type=wiki" in html or "/?q=%23git&type=wiki" in html
    assert "wiki/more.md" in html                                  # the page list on the side


@pytest.mark.tier1
def test_without_signing_in_the_wiki_asks_to_sign_in_and_a_private_task_hides_it(pool: _Courses) -> None:
    _push(pool, {"wiki.md": MAIN.encode()})
    status, _html = _page(_browser(pool, None), f"{pool.url}/web/wiki/bob/git-init/wiki.md")
    assert status == 200 and "/web/login" in _html  # noqa: PLR2004   (the login form)
    pool.push("bob/solo", "1", image="s")                      # not in a course: may go private
    _push(pool, {"wiki.md": MAIN.encode()}, repo="bob/solo")
    assert pool.call("PUT", "/revisions/bob/solo", "bob", {"visibility": "private"})[0] == 200  # noqa: PLR2004
    assert _page(_browser(pool, "eve"), f"{pool.url}/web/wiki/bob/solo/wiki.md")[0] == 404  # noqa: PLR2004
    assert _http("GET", f"{pool.url}/wiki/bob/solo", token=pool.tok["eve"])[0] == 404  # noqa: PLR2004
    assert _page(_browser(pool, "bob"), f"{pool.url}/web/wiki/bob/solo/wiki.md")[0] == 200  # noqa: PLR2004


@pytest.mark.tier1
def test_hiding_the_sources_does_not_hide_the_wiki(pool: _Courses) -> None:
    _push(pool, {"wiki.md": MAIN.encode()})
    assert pool.call("PUT", "/revisions/bob/git-init", "bob", {"hide_sources": True})[0] == 200  # noqa: PLR2004
    assert _page(_browser(pool, "eve"), f"{pool.url}/web/wiki/bob/git-init/wiki.md")[0] == 200  # noqa: PLR2004


@pytest.mark.tier1
def test_editing_in_the_browser_makes_a_version_with_its_author(pool: _Courses) -> None:
    _push(pool, {"wiki.md": MAIN.encode()})
    bob = _browser(pool, "bob")
    form = _page(bob, f"{pool.url}/web/wiki/bob/git-init/edit?page=wiki.md")[1]
    assert "name='base' value='1'" in form and "git init" in form
    status, _b, _h = _raw(bob, f"{pool.url}/web/wiki/bob/git-init/edit",
                          {"page": "wiki.md", "base": "1", "text": MAIN + "\nЕщё строка.\n", "message": "дописал"})
    assert status == 200  # noqa: PLR2004
    history = _page(bob, f"{pool.url}/web/wiki/bob/git-init/history")[1]
    assert "дописал" in history and "bob" in history and "версия 2" in history
    diff = _page(bob, f"{pool.url}/web/wiki/bob/git-init/history/2")[1]
    assert "Ещё строка." in diff
    status, _b, _h = _raw(_browser(pool, "eve"), f"{pool.url}/web/wiki/bob/git-init/edit",
                          {"page": "wiki.md", "base": "2", "text": "чужое"})
    assert status == 403  # noqa: PLR2004
    assert _push(pool, {"wiki.md": b"x"}, base=2, user="eve")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_a_stale_save_shows_a_conflict_and_keeps_the_text(pool: _Courses) -> None:
    _push(pool, {"wiki.md": MAIN.encode()})
    bob = _browser(pool, "bob")
    _raw(bob, f"{pool.url}/web/wiki/bob/git-init/edit", {"page": "wiki.md", "base": "1", "text": "первая правка"})
    status, body, _h = _raw(bob, f"{pool.url}/web/wiki/bob/git-init/edit",
                            {"page": "wiki.md", "base": "1", "text": "моя вторая правка"})
    html = body.decode()
    assert status == 409 and "моя вторая правка" in html and "name='base' value='2'" in html  # noqa: PLR2004
    assert _push(pool, {"wiki.md": b"stale"}, base=1)[0] == 409  # noqa: PLR2004


@pytest.mark.tier1
def test_a_picture_is_served_as_a_picture_and_a_fake_one_is_refused(pool: _Courses) -> None:
    _push(pool, {"wiki.md": MAIN.encode(), "wiki/shot.png": PNG})
    status, body, headers = _raw(_browser(pool, "eve"), f"{pool.url}/web/wiki/bob/git-init/wiki/shot.png")
    assert (status, body, headers["Content-Type"], headers["X-Content-Type-Options"]) == (200, PNG, "image/png", "nosniff")
    assert _push(pool, {"wiki.md": MAIN.encode(), "wiki/evil.png": b"<html><script>1</script>"}, base=1)[0] == 400  # noqa: PLR2004


@pytest.mark.tier1
def test_a_get_never_changes_the_wiki(pool: _Courses) -> None:
    _push(pool, {"wiki.md": MAIN.encode()})
    bob = _browser(pool, "bob")
    _page(bob, f"{pool.url}/web/wiki/bob/git-init/edit?page=wiki.md&base=1&text=x")
    _page(bob, f"{pool.url}/web/wiki/bob/git-init/delete?page=wiki.md")
    assert pool.r.store.root.joinpath(".repos/bob/git-init/wiki/v1").is_dir()
    assert not pool.r.store.root.joinpath(".repos/bob/git-init/wiki/v2").exists()


@pytest.mark.tier1
def test_the_card_has_a_wiki_button(pool: _Courses) -> None:
    owner = _page(_browser(pool, "bob"), f"{pool.url}/web/image/bob/git-init:1")[1]
    assert "Создать wiki" in owner
    assert "/web/wiki/bob/git-init" not in _page(_browser(pool, "eve"), f"{pool.url}/web/image/bob/git-init:1")[1]
    _push(pool, {"wiki.md": MAIN.encode()})
    assert "href='/web/wiki/bob/git-init'" in _page(_browser(pool, "eve"), f"{pool.url}/web/image/bob/git-init:1")[1]


@pytest.mark.tier1
def test_deleting_the_task_keeps_its_wiki_and_a_fork_keeps_a_copy(pool: _Courses) -> None:
    _push(pool, {"wiki.md": MAIN.encode()})
    _push(pool, {"wiki.md": b"# v2\n"}, base=1)
    code, _ = _http("POST", f"{pool.url}/revisions/eve/git-init/fork", token=pool.tok["eve"],
                    body={"from": "bob/git-init:1_v1"})
    assert code == 201  # noqa: PLR2004
    eve = _page(_browser(pool, "eve"), f"{pool.url}/web/wiki/bob/../eve/git-init/history")
    assert eve[0] in (200, 404)
    assert "версия 2" in _page(_browser(pool, "eve"), f"{pool.url}/web/wiki/eve/git-init/history")[1]
    assert _http("DELETE", f"{pool.url}/task/bob/git-init/1", token=pool.tok["bob"])[0] == 200  # noqa: PLR2004
    # spec: the wiki goes only with the repository -- deleting a tag keeps it (review 2026-11-03)
    assert pool.r.store.root.joinpath(".repos/bob/git-init/wiki/v2").is_dir()
    assert pool.r.store.root.joinpath(".repos/eve/git-init/wiki/v2").is_dir()


@pytest.mark.tier1
def test_the_course_page_links_each_task_to_its_wiki(pool) -> None:
    """User 2026-11-05: «я не увидел wiki» -- the course list, where students look, links it."""
    _http("POST", f"{pool.url}/wiki/bob/git-init?base=0", token=pool.tok["bob"], data=pack({"wiki.md": b"# Git\n"}))
    html = _page(_browser(pool, "eve"), f"{pool.url}/c/bob/linux")[1]
    assert "href='/web/wiki/bob/git-init'" in html


@pytest.mark.tier1
def test_the_task_card_shows_the_wiki_under_the_readme(pool) -> None:
    """User 2026-11-05: «README идёт в о задании… а внизу сразу отображается wiki»."""
    _http("POST", f"{pool.url}/wiki/bob/git-init?base=0", token=pool.tok["bob"],
          data=pack({"wiki.md": "# Теория git\n\nСм. [шпаргалку](wiki/sheet.md).\n".encode(),
                     "wiki/sheet.md": b"# Sheet\n"}))
    html = _page(_browser(pool, "eve"), f"{pool.url}/web/image/bob/git-init:1")[1]
    readme, wiki = html.index("README.md"), html.index("Теория git")
    assert readme < wiki                                                    # the wiki comes under it
    assert 'href="/web/wiki/bob/git-init/wiki/sheet.md"' in html            # its links still lead home


def _block_wiki_setup(pool) -> tuple[str, str]:
    pool.push("bob/regex", "1", image="r", task="tr")
    hidden = pool.push("bob/draft", "1", image="d", task="td")
    assert hidden[0] == 201  # noqa: PLR2004
    view = pool.call("GET", "/courses/bob/linux", "bob")[1]
    first = view["blocks"][0]["id"]
    second = pool.call("POST", "/courses/bob/linux/blocks", "bob", {"name": "Regex"})[1]["id"]
    for repo in ("bob/regex", "bob/draft"):
        pool.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": repo, "tag": "1", "block_id": second})
    pool.call("PUT", "/courses/bob/linux/tasks/bob/draft:1", "bob", {"hidden": True})
    for repo, title in (("bob/git-init", "Теория git"), ("bob/regex", "Регулярки"), ("bob/draft", "Черновик")):
        _http("POST", f"{pool.url}/wiki/{repo}?base=0", token=pool.tok["bob"],
              data=pack({"wiki.md": f"# {title}\n\nПервый абзац про {title}.\n".encode()}))
    return first, second


@pytest.mark.tier1
def test_the_course_wiki_gathers_its_tasks_wikis_by_block(pool) -> None:
    """User 2026-11-05: «wiki ссылки курса и блока — нажимаешь на wiki блока — все wiki заданий со ссылками»."""
    _first, second = _block_wiki_setup(pool)
    html = _page(_browser(pool, "eve"), f"{pool.url}/c/bob/linux/wiki")[1]
    assert html.index("Теория git") < html.index("Регулярки")                  # course order, by block
    assert "href='/web/wiki/bob/regex'" in html and "Первый абзац про Регулярки" in html
    assert "<details class='card item-card wiki-fold'" in html and "<h1>Регулярки</h1>" in html   # unfolds in place
    assert "Черновик" not in html                                               # a hidden task stays hidden
    block = _page(_browser(pool, "eve"), f"{pool.url}/c/bob/linux/wiki?block={second}")[1]
    assert "Регулярки" in block and "Теория git" not in block
    course = _page(_browser(pool, "eve"), f"{pool.url}/c/bob/linux")[1]
    assert "href='/c/bob/linux/wiki'" in course and f"href='/c/bob/linux/wiki?block={second}'" in course
