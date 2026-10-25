"""Tier1: the /courses API -- create, see, join, request, members, blocks, tasks, proposals (spec §4-§7)."""
from pathlib import Path

import pytest

from hashpass.registry import era
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.revisions import RepoIndex
from tests.registry.test_push_commit import _http, _Pool


class _Courses(_Pool):
    def __init__(self, registry, tmp_path: Path) -> None:
        super().__init__(registry, tmp_path)
        for user in ("kid", "max", "ann"):
            registry.users.add(user, "pw-correct1", role="student")
            self.tok[user] = RemoteRegistry(self.url).login(user, "pw-correct1")

    def call(self, method: str, path: str, user: str | None, body: dict | None = None) -> tuple[int, dict]:
        return _http(method, f"{self.url}{path}", token=self.tok[user] if user else None,
                     body=body if body is not None else ({} if method in ("POST", "PUT") else None))


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/git-init", "1", image="one", task="t1")
    p.push("bob/git-init", "1", image="two", task="t2")
    p.push("eve/regex", "1", image="re", task="r1", user="eve")
    return p


def _course(pool: _Courses, visibility: str = "public") -> str:
    code, body = pool.call("POST", "/courses", "bob", {"name": "linux", "title": "Linux",
                                                      "visibility": visibility})
    assert code == 201, body  # noqa: PLR2004
    return "/courses/bob/linux"


@pytest.mark.tier1
def test_create_list_and_view(pool: _Courses) -> None:
    path = _course(pool)
    assert pool.call("POST", "/courses", "bob", {"name": "linux"})[0] == 400  # noqa: PLR2004
    assert [c["ref"] for c in pool.call("GET", "/courses", "kid")[1]["courses"]] == ["bob/linux"]
    code, view = pool.call("GET", path, None)                       # a public course: anyone looks
    assert (code, view["title"], view["blocks"]) == (200, "Linux", [])


@pytest.mark.tier1
def test_author_adds_directly_others_propose(pool: _Courses) -> None:
    path = _course(pool)
    block = pool.call("POST", f"{path}/blocks", "bob", {"name": "Git"})[1]["id"]
    code, body = pool.call("POST", f"{path}/tasks", "bob", {"repo": "bob/git-init", "tag": "1",
                                                           "block_id": block})
    assert (code, body["task"]["n"]) == (201, 2)                    # newest revision by default
    code, body = pool.call("POST", f"{path}/tasks", "eve", {"repo": "eve/regex", "tag": "1",
                                                           "block_id": block, "comment": "возьмите"})
    assert (code, body["proposal"]["state"]) == (201, "open")
    view = pool.call("GET", path, "kid")[1]
    assert [t["ref"] for b in view["blocks"] for t in b["tasks"]] == ["bob/git-init:1"]
    assert view["proposals"] == []                                   # not theirs
    pid = body["proposal"]["id"]
    assert pool.call("POST", f"{path}/proposals/{pid}", "eve", {"action": "accept"})[0] == 403  # noqa: PLR2004
    assert pool.call("POST", f"{path}/proposals/{pid}", "bob", {"action": "accept"})[0] == 200  # noqa: PLR2004
    view = pool.call("GET", path, "kid")[1]
    assert [t["ref"] for b in view["blocks"] for t in b["tasks"]] == ["bob/git-init:1", "eve/regex:1"]


@pytest.mark.tier1
def test_auto_update_and_pinned(pool: _Courses) -> None:
    path = _course(pool)
    block = pool.call("POST", f"{path}/blocks", "bob", {"name": "Git"})[1]["id"]
    pool.call("POST", f"{path}/tasks", "bob", {"repo": "bob/git-init", "tag": "1", "n": 1,
                                               "block_id": block})
    task = pool.call("GET", path, "kid")[1]["blocks"][0]["tasks"][0]
    assert task["revision"] == "bob/git-init:1_v2"                  # follows the newest
    pool.call("PUT", f"{path}/tasks/bob/git-init:1", "bob", {"pinned": True})
    view = pool.call("GET", path, "bob")[1]
    assert view["blocks"][0]["tasks"][0]["revision"] == "bob/git-init:1_v1"
    assert view["updates"] == [{"repo": "bob/git-init", "tag": "1", "latest": 2}]
    pool.call("PUT", f"{path}/tasks/bob/git-init:1", "bob", {"n": 2})
    assert pool.call("GET", path, "bob")[1]["updates"] == []


@pytest.mark.tier1
def test_private_course_peek_request_invite(pool: _Courses) -> None:
    path = _course(pool, "private")
    code, peek = pool.call("GET", path, "kid")
    assert (code, peek["access"], "blocks" in peek) == (200, "request", False)
    assert pool.call("GET", "/courses", "kid")[1]["courses"] == []   # not in search
    assert pool.call("POST", f"{path}/requests", "kid", {"comment": "можно?"})[0] == 201  # noqa: PLR2004
    assert pool.call("GET", path, "kid")[1]["access"] == "requested"
    assert pool.call("POST", f"{path}/requests/kid", "kid", {"accept": True})[0] == 403  # noqa: PLR2004
    assert pool.call("POST", f"{path}/requests/kid", "bob", {"accept": True})[0] == 200  # noqa: PLR2004
    assert "blocks" in pool.call("GET", path, "kid")[1]
    invite = pool.call("GET", path, "bob")[1]["invite"]
    assert pool.call("POST", f"{path}/join", "max", {"invite": "nope"})[0] == 403  # noqa: PLR2004
    assert pool.call("POST", f"{path}/join", "max", {"invite": invite})[0] == 200  # noqa: PLR2004
    assert "blocks" in pool.call("GET", path, "max")[1]


@pytest.mark.tier1
def test_members_and_roles(pool: _Courses) -> None:
    path = _course(pool)
    assert pool.call("PUT", f"{path}/members/ann", "max", {"role": "maintainer"})[0] == 403  # noqa: PLR2004
    assert pool.call("PUT", f"{path}/members/ann", "bob", {"role": "maintainer"})[0] == 200  # noqa: PLR2004
    assert pool.call("POST", f"{path}/blocks", "ann", {"name": "B"})[0] == 201  # noqa: PLR2004
    assert pool.call("PUT", path, "ann", {"title": "x"})[0] == 200    # settings: the `content` box  # noqa: PLR2004
    assert pool.call("DELETE", path, "ann")[0] == 403                 # deleting: the owner only  # noqa: PLR2004
    assert pool.call("PUT", f"{path}/members/nobody", "bob", {"role": "member"})[0] == 404  # noqa: PLR2004


@pytest.mark.tier1
def test_private_image_only_in_a_private_course(pool: _Courses) -> None:
    with RepoIndex(pool.r.store.root / ".repos", "bob/git-init").locked() as idx:
        idx.set_meta(visibility="private")
    public = _course(pool)
    code, body = pool.call("POST", f"{public}/tasks", "bob", {"repo": "bob/git-init", "tag": "1"})
    assert code == 400 and "приватный" in body["error"]  # noqa: PLR2004
    pool.call("POST", "/courses", "bob", {"name": "closed", "visibility": "private"})
    assert pool.call("POST", "/courses/bob/closed/tasks", "bob",
                     {"repo": "bob/git-init", "tag": "1"})[0] == 201  # noqa: PLR2004
    code, body = pool.call("PUT", "/courses/bob/closed", "bob", {"visibility": "public"})
    assert code == 409 and "bob/git-init:1" in body["error"]  # noqa: PLR2004


@pytest.mark.tier1
def test_block_must_be_empty_to_remove(pool: _Courses) -> None:
    path = _course(pool)
    block = pool.call("POST", f"{path}/blocks", "bob", {"name": "Git"})[1]["id"]
    pool.call("POST", f"{path}/tasks", "bob", {"repo": "bob/git-init", "tag": "1", "block_id": block})
    code, body = pool.call("DELETE", f"{path}/blocks/{block}", "bob")
    assert code == 400 and "не пуст" in body["error"]  # noqa: PLR2004
    pool.call("DELETE", f"{path}/tasks/bob/git-init:1", "bob")
    assert pool.call("DELETE", f"{path}/blocks/{block}", "bob")[0] == 200  # noqa: PLR2004


@pytest.mark.tier1
def test_stale_rev_is_a_conflict(pool: _Courses) -> None:
    path = _course(pool)
    rev = pool.call("GET", path, "bob")[1]["rev"]
    pool.call("PUT", path, "bob", {"title": "A", "rev": rev})
    code, _ = pool.call("PUT", path, "bob", {"title": "B", "rev": rev})
    assert code == 409  # noqa: PLR2004


@pytest.mark.tier1
def test_courses_are_off_unless_switched_on(pool: _Courses, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(era, "COURSES", False)
    code, body = pool.call("GET", "/courses", "bob")
    assert code == 404 and "не включены" in body["error"]  # noqa: PLR2004


@pytest.mark.tier1
def test_layout_reorders_and_moves_between_blocks(pool: _Courses) -> None:
    path = _course(pool)
    one = pool.call("POST", f"{path}/blocks", "bob", {"name": "One"})[1]["id"]
    two = pool.call("POST", f"{path}/blocks", "bob", {"name": "Two"})[1]["id"]
    pool.call("POST", f"{path}/tasks", "bob", {"repo": "bob/git-init", "tag": "1", "block_id": one})
    pool.call("POST", f"{path}/tasks", "bob", {"repo": "eve/regex", "tag": "1", "block_id": one})
    rev = pool.call("GET", path, "bob")[1]["rev"]
    layout = [{"id": two, "tasks": ["eve/regex:1"]}, {"id": one, "tasks": ["bob/git-init:1"]}]
    assert pool.call("PUT", f"{path}/layout", "kid", {"blocks": layout})[0] == 403  # noqa: PLR2004
    assert pool.call("PUT", f"{path}/layout", "bob", {"blocks": layout, "rev": rev})[0] == 200  # noqa: PLR2004
    view = pool.call("GET", path, "bob")[1]
    assert [(b["name"], [t["ref"] for t in b["tasks"]]) for b in view["blocks"]] == [
        ("Two", ["eve/regex:1"]), ("One", ["bob/git-init:1"])]
    code, body = pool.call("PUT", f"{path}/layout", "bob", {"blocks": layout[:1]})
    assert code == 400 and "не совпадает" in body["error"]  # noqa: PLR2004


@pytest.mark.tier1
def test_the_web_session_cookie_works_for_the_api(pool: _Courses) -> None:
    import urllib.request  # noqa: PLC0415
    path = _course(pool, "private")
    req = urllib.request.Request(f"{pool.url}/web/login", data=b"user=bob&password=pw-correct1",  # noqa: S310
                                 method="POST")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    opener.open(req, timeout=10)
    with opener.open(f"{pool.url}{path}", timeout=10) as resp:
        assert b'"role": "owner"' in resp.read()


@pytest.mark.tier1
def test_a_cross_site_form_post_does_not_act_for_the_user(pool: _Courses) -> None:
    """Codex 2026-10-22: a plain form POST carries the session cookie; it must not count."""
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    _course(pool, "private")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    opener.open(urllib.request.Request(f"{pool.url}/web/login",  # noqa: S310
                                       data=b"user=kid&password=pw-correct1"), timeout=10)
    form = urllib.parse.urlencode({"comment": "csrf"}).encode()
    req = urllib.request.Request(f"{pool.url}/courses/bob/linux/requests", data=form,  # noqa: S310
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        opener.open(req, timeout=10)
    assert exc.value.code == 401  # noqa: PLR2004
    assert pool.call("GET", "/courses/bob/linux", "bob")[1]["requests"] == []
