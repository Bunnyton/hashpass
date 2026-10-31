"""Tier1: mirrors and forks of a course over HTTP (spec 2026-10-31)."""
# ruff: noqa: PLR2004
from pathlib import Path

import pytest

from tests.registry.test_course_api import _course, _Courses


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/git-init", "1", image="one", task="t1")
    p.push("bob/git-init", "1", image="two", task="t2")
    p.push("eve/regex", "1", image="re", task="r1", user="eve")
    return p


def _with_task(pool: _Courses, visibility: str = "public") -> str:
    path = _course(pool, visibility)
    block = pool.call("POST", f"{path}/blocks", "bob", {"name": "Git"})[1]["id"]
    pool.call("POST", f"{path}/tasks", "bob", {"repo": "bob/git-init", "tag": "1", "block_id": block})
    return path


def _tasks(view: dict) -> list[str]:
    return [t["ref"] for b in view.get("blocks", []) for t in b["tasks"]]


@pytest.mark.tier1
def test_mirror_and_fork_created_with_origin(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("PUT", path, "bob", {"allow_forks": True})
    code, made = pool.call("POST", f"{path}/mirror", "kid", {"name": "linux-m"})
    assert (code, made["ref"], made["origin"]["kind"], made["origin"]["ref"]) == (201, "kid/linux-m", "mirror",
                                                                                   "bob/linux")
    view = pool.call("GET", "/courses/kid/linux-m", "kid")[1]
    assert (_tasks(view), view["title"], view["origin"]["owner"], view["origin"]["linked"]) == (
        ["bob/git-init:1"], "Linux", "bob", True)
    code, made = pool.call("POST", f"{path}/fork", "kid", {"name": "linux-f", "title": "Мой Linux"})
    assert (code, made["title"], made["origin"]["kind"]) == (201, "Мой Linux", "fork")
    assert pool.call("GET", "/courses", "kid")[1]["courses"][0]["origin"] is None    # bob/linux itself


@pytest.mark.tier1
def test_forks_off_by_default_mirrors_on(pool: _Courses) -> None:
    path = _with_task(pool)
    code, body = pool.call("POST", f"{path}/fork", "kid", {"name": "f"})
    assert (code, body["error"]) == (403, "автор курса не разрешает форки")
    assert pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})[0] == 201
    pool.call("PUT", path, "bob", {"allow_forks": True, "allow_mirrors": False})
    code, body = pool.call("POST", f"{path}/mirror", "kid", {"name": "m2"})
    assert (code, body["error"]) == (403, "автор курса не разрешает зеркала")
    assert pool.call("POST", f"{path}/fork", "kid", {"name": "f"})[0] == 201
    settings = pool.call("GET", path, "bob")[1]["settings"]
    assert (settings["allow_mirrors"], settings["allow_forks"]) == (False, True)
    assert pool.call("POST", f"{path}/fork", None, {"name": "x"})[0] == 401


@pytest.mark.tier1
def test_private_source_copy_must_be_private(pool: _Courses) -> None:
    path = _with_task(pool, "private")
    assert pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})[0] in {401, 403, 404}   # cannot see it
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})
    code, body = pool.call("POST", f"{path}/mirror", "kid", {"name": "m", "visibility": "public"})
    assert (code, body["error"]) == (400, "копия приватного курса — только приватная")
    code, made = pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    assert (code, made["visibility"]) == (201, "private")


@pytest.mark.tier1
def test_mirror_of_mirror_points_at_root(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    code, made = pool.call("POST", "/courses/kid/m/mirror", "max", {"name": "m2"})
    assert (code, made["origin"]["ref"]) == (201, "bob/linux")
    pool.call("PUT", path, "bob", {"allow_mirrors": False})
    assert pool.call("POST", "/courses/kid/m/mirror", "ann", {"name": "m3"})[0] == 403   # the root's say


@pytest.mark.tier1
def test_fork_of_mirror_is_fork_of_root(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    assert pool.call("POST", "/courses/kid/m/fork", "max", {"name": "f"})[0] == 403      # the root forbids
    pool.call("PUT", path, "bob", {"allow_forks": True})
    code, made = pool.call("POST", "/courses/kid/m/fork", "max", {"name": "f"})
    assert (code, made["origin"]["ref"], made["origin"]["kind"]) == (201, "bob/linux", "fork")
    assert pool.call("POST", "/courses/max/f/fork", "ann", {"name": "ff"})[0] == 403      # the fork's own say
    pool.call("PUT", "/courses/max/f", "max", {"allow_forks": True})
    code, made = pool.call("POST", "/courses/max/f/fork", "ann", {"name": "ff"})
    assert (code, made["origin"]["ref"]) == (201, "max/f")


@pytest.mark.tier1
def test_origin_unlinked_for_who_cannot_see_parent(pool: _Courses) -> None:
    path = _with_task(pool, "private")
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    pool.call("PUT", "/courses/kid/m/members/max", "kid", {"role": "member"})
    origin = pool.call("GET", "/courses/kid/m", "max")[1]["origin"]
    assert (origin["linked"], origin["title"], origin["owner"]) == (False, "Linux", "bob")


@pytest.mark.tier1
def test_parent_lists_copies(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("PUT", path, "bob", {"allow_forks": True})
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    pool.call("POST", f"{path}/fork", "max", {"name": "f"})
    copies = pool.call("GET", path, "ann")[1]["copies"]
    assert (copies["mirrors"], copies["forks"]) == (1, 1)
    assert sorted(c["ref"] for c in copies["list"]) == ["kid/m", "max/f"]


@pytest.mark.tier1
def test_rename_parent_keeps_origin(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    assert pool.call("PUT", path, "bob", {"name": "linux2"})[0] == 200
    origin = pool.call("GET", "/courses/kid/m", "kid")[1]["origin"]
    assert (origin["ref"], origin["linked"]) == ("bob/linux2", True)


@pytest.mark.tier1
def test_mirror_structure_routes_forbidden(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    m = "/courses/kid/m"
    block = pool.call("GET", m, "kid")[1]["blocks"][0]["id"]
    says = "это зеркало курса bob/linux — задания и порядок меняет его автор"
    for method, url, body in (("POST", f"{m}/tasks", {"repo": "eve/regex", "tag": "1", "block_id": block}),
                              ("POST", f"{m}/blocks", {"name": "Свой"}),
                              ("PUT", f"{m}/blocks/{block}", {"name": "Переименован"}),
                              ("DELETE", f"{m}/blocks/{block}", None),
                              ("PUT", f"{m}/layout", {"blocks": []}),
                              ("PUT", f"{m}/tasks/bob/git-init:1", {"hidden": True}),
                              ("DELETE", f"{m}/tasks/bob/git-init:1", None),
                              ("PUT", m, {"auto_update": False})):
        for who in ("kid", "max"):
            code, said = pool.call(method, url, who, body)
            assert (code, said.get("error")) == (403, says) or (who == "max" and code == 403), (method, url, who)
    assert pool.call("PUT", f"{m}/blocks/{block}", "kid", {"open": False})[0] == 200   # its own schedule
    assert pool.call("PUT", m, "kid", {"title": "Группа 7"})[0] == 200
    view = pool.call("GET", m, "kid")[1]
    assert (view["blocks"][0]["open"], view["title"], _tasks(view)) == (False, "Группа 7", ["bob/git-init:1"])


@pytest.mark.tier1
def test_parent_change_reaches_mirror_over_http(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    block = pool.call("GET", path, "bob")[1]["blocks"][0]["id"]
    pool.call("POST", f"{path}/tasks", "bob", {"repo": "eve/regex", "tag": "1", "block_id": block})
    assert _tasks(pool.call("GET", "/courses/kid/m", "max")[1]) == ["bob/git-init:1", "eve/regex:1"]


# -- the parent's privacy, removed access, deletion ---------------------------

@pytest.mark.tier1
def test_parent_private_makes_copies_private(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("PUT", path, "bob", {"allow_forks": True})
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    pool.call("POST", f"{path}/fork", "max", {"name": "f"})
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})     # so the mirror stays open
    pool.call("PUT", f"{path}/members/max", "bob", {"role": "member"})
    assert pool.call("PUT", path, "bob", {"visibility": "private"})[0] == 200
    for ref, owner in (("kid/m", "kid"), ("max/f", "max")):
        view = pool.call("GET", f"/courses/{ref}", owner)[1]
        assert view["visibility"] == "private"
        assert view["history"][0]["what"] == "исходный курс стал приватным — курс тоже"


def _revoked_setup(pool: _Courses) -> str:
    path = _with_task(pool, "private")
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    pool.call("PUT", "/courses/kid/m/members/max", "kid", {"role": "member"})
    pool.call("DELETE", f"{path}/members/kid", "bob")
    return path


@pytest.mark.tier1
def test_removed_member_mirror_closed(pool: _Courses) -> None:
    path = _revoked_setup(pool)
    view = pool.call("GET", "/courses/kid/m", "max")[1]
    assert (view["origin"]["revoked"], view["blocks"]) == (True, [])
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})
    view = pool.call("GET", "/courses/kid/m", "max")[1]
    assert (view["origin"]["revoked"], _tasks(view)) == (False, ["bob/git-init:1"])


@pytest.mark.tier1
def test_revoked_mirror_serves_no_task(pool: _Courses) -> None:
    _revoked_setup(pool)
    _code, body = pool.call("GET", "/catalog?course=kid/m", "max")
    assert [r for r in body.get("catalog", []) if r.get("ref") == "bob/git-init:1"] == []
    digest = pool.call("GET", "/courses/bob/linux", "bob")[1]  # the parent's revision, for the record
    assert digest["blocks"]
    code, body = pool.call("POST", "/submit", "max", {"task_ref": "bob/git-init:1", "course": "kid/m",
                                                      "digest": "x", "passed": True})
    assert body.get("status") != "passed"


@pytest.mark.tier1
def test_parent_deleted_copies_gone_and_editable(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    assert pool.call("DELETE", path, "bob")[0] == 200
    view = pool.call("GET", "/courses/kid/m", "kid")[1]
    assert (view["origin"]["gone"], view["origin"]["title"], _tasks(view)) == (True, "Linux", ["bob/git-init:1"])
    block = view["blocks"][0]["id"]
    assert pool.call("POST", "/courses/kid/m/tasks", "kid",
                     {"repo": "eve/regex", "tag": "1", "block_id": block})[0] == 201


@pytest.mark.tier1
def test_parent_deleted_mirror_of_fork_untouched(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("PUT", path, "bob", {"allow_forks": True})
    pool.call("POST", f"{path}/fork", "kid", {"name": "f"})
    pool.call("POST", "/courses/kid/f/mirror", "max", {"name": "mf"})
    pool.call("DELETE", path, "bob")
    assert pool.call("GET", "/courses/kid/f", "kid")[1]["origin"]["gone"] is True
    mirror = pool.call("GET", "/courses/max/mf", "max")[1]
    assert (mirror["origin"]["gone"], mirror["origin"]["ref"]) == (False, "kid/f")
    block = pool.call("GET", "/courses/kid/f", "kid")[1]["blocks"][0]["id"]
    pool.call("POST", "/courses/kid/f/tasks", "kid", {"repo": "eve/regex", "tag": "1", "block_id": block})
    assert _tasks(pool.call("GET", "/courses/max/mf", "max")[1]) == ["bob/git-init:1", "eve/regex:1"]


@pytest.mark.tier1
def test_disable_and_delete_existing(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("PUT", path, "bob", {"allow_forks": True})
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    pool.call("POST", f"{path}/fork", "max", {"name": "f"})
    code, copies = pool.call("GET", f"{path}/copies", "bob")
    assert (code, copies["mirrors"], copies["forks"]) == (200, ["kid/m"], ["max/f"])
    assert copies["students"] == {"kid/m": 1, "max/f": 1}
    assert pool.call("GET", f"{path}/copies", "kid")[0] == 403
    assert pool.call("PUT", path, "kid", {"allow_mirrors": False, "delete_existing": ["mirrors"]})[0] == 403
    code, body = pool.call("PUT", path, "bob", {"allow_mirrors": False, "delete_existing": ["mirrors"]})
    assert (code, body["deleted"]) == (200, ["kid/m"])
    assert pool.call("GET", "/courses/kid/m", "kid")[0] == 404
    assert pool.call("GET", "/courses/max/f", "max")[0] == 200
