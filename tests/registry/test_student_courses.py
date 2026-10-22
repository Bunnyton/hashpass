"""Tier1/2: a student adds a course by link and works through it -- catalog, pull, credit (spec §9)."""
from pathlib import Path

import pytest

from hashpass import cli, my_courses
from hashpass.imagestore.store import ImageStore
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry, use_course
from hashpass.registry.revisions import RepoIndex
from tests.registry.test_course_api import _Courses


@pytest.mark.tier1
def test_parse_course_links() -> None:
    assert my_courses.parse_link("https://pool.example:8080/c/bob/linux?invite=abc") == (
        "https://pool.example:8080", "bob/linux", "abc")
    assert my_courses.parse_link("pool.example/c/bob/linux/") == ("https://pool.example", "bob/linux", "")
    with pytest.raises(ValueError, match="не ссылка на курс"):
        my_courses.parse_link("https://pool.example/web/images")


@pytest.mark.tier1
def test_choose_forget_and_activate(tmp_path: Path) -> None:
    url = "http://127.0.0.1:9"
    my_courses.choose(tmp_path, url, "bob/linux")
    my_courses.choose(tmp_path, url, "eve/git")
    assert (my_courses.mine(tmp_path, url), my_courses.current(tmp_path, url)) == (
        ["bob/linux", "eve/git"], "eve/git")
    assert RemoteRegistry(url).course == "eve/git"
    my_courses.forget(tmp_path, url, "eve/git")
    assert my_courses.current(tmp_path, url) == "bob/linux"
    use_course(url, None)
    assert my_courses.activate(tmp_path, url) == "bob/linux"
    assert RemoteRegistry(url).course == "bob/linux"
    use_course(url, None)


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/git-init", "1", image="one", task="t1")
    p.push("bob/git-init", "1", image="two", task="t2")
    p.call("POST", "/courses", "bob", {"name": "linux", "visibility": "private"})
    p.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": "bob/git-init", "tag": "1", "n": 1})
    p.call("PUT", "/courses/bob/linux/tasks/bob/git-init:1", "bob", {"pinned": True})
    yield p
    use_course(p.url, None)


def _env(tmp_path: Path, pool: _Courses) -> cli.Home:
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "kid")}, default_home=tmp_path)
    cli.save_pool(env, pool.url, "kid")
    RemoteRegistry(pool.url, cache=CredentialCache(env.creds)).login("kid", "pw-correct1")
    return env


@pytest.mark.tier2
def test_add_by_invite_then_catalog_pull_and_credit_through_the_course(pool: _Courses, tmp_path: Path) -> None:
    env = _env(tmp_path, pool)
    invite = pool.call("GET", "/courses/bob/linux", "bob")[1]["invite"]
    said: list[str] = []
    io = cli.Io(read=lambda _p: "", write=said.append, clock=lambda: "")
    assert cli.cmd_course_add(env, f"{pool.url}/c/bob/linux?invite={invite}", io) == 0
    assert my_courses.current(env.root, pool.url) == "bob/linux"
    client = RemoteRegistry(pool.url, token=pool.tok["kid"])
    assert client.course == "bob/linux"
    tok = pool.tok["kid"]
    assert [r["ref"] for r in client.catalog(token=tok)] == ["bob/git-init:1"]
    store = ImageStore(env.images)
    client.pull("bob/git-init:1", store)
    assert store.get("bob/git-init:1").version == "1_v1"            # the course's pinned revision
    digest = RepoIndex(pool.r.store.root / ".repos", "bob/git-init").get("1", 1).task_digest
    assert client.submit("bob/git-init:1", digest, passed=True, token=tok)["status"] == "passed"
    rec = client.progress(token=tok)["kid"]["bob/git-init:1"]
    assert rec["course"] == "bob/linux"


@pytest.mark.tier2
def test_a_private_course_without_invite_asks_for_access(pool: _Courses, tmp_path: Path) -> None:
    env = _env(tmp_path, pool)
    said: list[str] = []
    io = cli.Io(read=lambda _p: "я из ИТ-21", write=said.append, clock=lambda: "")
    assert cli.cmd_course_add(env, f"{pool.url}/c/bob/linux", io) == 0
    assert "заявка" in said[-1]
    assert [r["user"] for r in pool.call("GET", "/courses/bob/linux", "bob")[1]["requests"]] == ["kid"]


@pytest.mark.tier2
def test_a_newcomer_registers_right_from_the_course_link(pool: _Courses, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Was: `hashpass add <link>` without an account ended in a bare «HTTP Error 401»."""
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "new")}, default_home=tmp_path)
    pool.call("PUT", "/courses/bob/linux", "bob", {"visibility": "public"})
    monkeypatch.setattr(cli.getpass, "getpass", lambda _p: "pw-correct1!")
    answers = iter(["newbie", "ИУ7-31"])
    said: list[str] = []
    io = cli.Io(read=lambda _p: next(answers), write=said.append, clock=lambda: "")
    assert cli.cmd_course_add(env, f"{pool.url}/c/bob/linux", io) == 0
    assert pool.r.users.has("newbie")
    assert my_courses.current(env.root, pool.url) == "bob/linux"
    assert "регистр" in "".join(said).lower()
