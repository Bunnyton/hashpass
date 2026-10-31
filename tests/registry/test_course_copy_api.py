"""Tier1: mirrors and forks of a course over HTTP (spec 2026-10-31)."""
# ruff: noqa: PLR2004
from pathlib import Path

import pytest

from hashpass.registry.revisions import RepoIndex
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
    path = _revoked_setup(pool)
    _code, body = pool.call("GET", "/catalog?course=kid/m", "max")
    assert [r for r in body.get("catalog", []) if r.get("ref") == "bob/git-init:1"] == []
    digest = RepoIndex(pool.r.store.root / ".repos", "bob/git-init").get("1", 2).task_digest
    submit = {"task_ref": "bob/git-init:1", "course": "kid/m", "digest": digest, "passed": True}
    assert pool.call("POST", "/submit", "max", submit)[1].get("status") != "passed"
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})             # access back
    assert pool.call("POST", "/submit", "max", submit)[1].get("status") == "passed"


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


# -- a fork pulls its parent's changes -----------------------------------------

def _fork(pool: _Courses) -> tuple[str, str]:
    path = _with_task(pool)
    pool.call("PUT", path, "bob", {"allow_forks": True})
    pool.call("POST", f"{path}/fork", "kid", {"name": "f"})
    return path, "/courses/kid/f"


@pytest.mark.tier1
def test_sync_shows_and_applies_parent_changes(pool: _Courses) -> None:
    path, fork = _fork(pool)
    block = pool.call("GET", path, "bob")[1]["blocks"][0]["id"]
    pool.call("POST", f"{path}/tasks", "bob", {"repo": "eve/regex", "tag": "1", "block_id": block})
    code, sync = pool.call("GET", f"{fork}/sync", "kid")
    assert (code, sync["behind"], [c["text"] for c in sync["changes"]], sync["conflicts"]) == (
        200, 1, ["добавлено задание eve/regex:1 в блок «Git»"], [])
    assert pool.call("GET", fork, "kid")[1]["origin"]["behind"] == 1
    code, done = pool.call("POST", f"{fork}/sync", "kid", {})
    assert (code, done["applied"], done["conflicts"]) == (200, 1, [])
    view = pool.call("GET", fork, "kid")[1]
    assert (_tasks(view), view["history"][0]["what"]) == (["bob/git-init:1", "eve/regex:1"],
                                                          "подтянуто из bob/linux: изменений 1, конфликтов 0")


@pytest.mark.tier1
def test_sync_conflict_keeps_fork_version(pool: _Courses) -> None:
    path, fork = _fork(pool)
    block = pool.call("GET", path, "bob")[1]["blocks"][0]["id"]
    pool.call("PUT", f"{path}/tasks/bob/git-init:1", "bob", {"pinned": True})
    pool.call("PUT", f"{path}/blocks/{block}", "bob", {"name": "Гит"})
    pool.call("PUT", f"{fork}/tasks/bob/git-init:1", "kid", {"pinned": True})   # the same end: no conflict
    pool.call("PUT", f"{fork}/blocks/{block}", "kid", {"name": "Мой Git"})
    done = pool.call("POST", f"{fork}/sync", "kid", {})[1]
    assert [(c["op"], c["new"]) for c in done["conflicts"]] == [("block_rename", "Гит")]
    view = pool.call("GET", fork, "kid")[1]
    assert (view["blocks"][0]["name"], view["blocks"][0]["tasks"][0]["pinned"]) == ("Мой Git", True)


@pytest.mark.tier1
def test_sync_resets_base(pool: _Courses) -> None:
    path, fork = _fork(pool)
    pool.call("PUT", path, "bob", {"auto_update": False})
    pool.call("POST", f"{fork}/sync", "kid", {})
    assert pool.call("GET", f"{fork}/sync", "kid")[1]["behind"] == 0
    assert pool.call("GET", fork, "kid")[1]["origin"]["behind"] == 0


@pytest.mark.tier1
def test_sync_needs_content(pool: _Courses) -> None:
    _path, fork = _fork(pool)
    assert pool.call("GET", f"{fork}/sync", "max")[0] == 403
    assert pool.call("POST", f"{fork}/sync", "max", {})[0] == 403
    assert "behind" not in (pool.call("GET", fork, "max")[1]["origin"] or {})


@pytest.mark.tier1
def test_sync_on_mirror_or_course_400(pool: _Courses) -> None:
    path = _with_task(pool)
    pool.call("POST", f"{path}/mirror", "kid", {"name": "m"})
    code, body = pool.call("GET", "/courses/kid/m/sync", "kid")
    assert (code, body["error"]) == (400, "это не форк")
    assert pool.call("GET", f"{path}/sync", "bob")[0] == 400


@pytest.mark.tier1
def test_sync_parent_gone_or_closed(pool: _Courses) -> None:
    path, fork = _fork(pool)
    pool.call("PUT", f"{path}/members/kid", "bob", {"role": "member"})
    pool.call("PUT", path, "bob", {"visibility": "private"})
    pool.call("DELETE", f"{path}/members/kid", "bob")
    code, body = pool.call("GET", f"{fork}/sync", "kid")
    assert (code, body["error"]) == (403, "нет доступа к исходному курсу")
    pool.call("DELETE", path, "bob")
    code, body = pool.call("POST", f"{fork}/sync", "kid", {})
    assert (code, body["error"]) == (400, "исходный курс удалён")


# -- a whole fork offered back -------------------------------------------------

def _offered(pool: _Courses) -> tuple[str, str, str]:
    path, fork = _fork(pool)
    block = pool.call("GET", fork, "kid")[1]["blocks"][0]["id"]
    pool.call("POST", f"{fork}/tasks", "kid", {"repo": "eve/regex", "tag": "1", "block_id": block})
    code, body = pool.call("POST", f"{fork}/merge", "kid", {"comment": "добавил regex"})
    assert code == 201, body
    return path, fork, body["merge"]["id"]


@pytest.mark.tier1
def test_merge_request_seen_and_taken(pool: _Courses) -> None:
    path, fork, mid = _offered(pool)
    code, body = pool.call("GET", f"{path}/merges", "bob")
    req = body["merges"][0]
    assert (code, req["from_ref"], req["stale"], [c["text"] for c in req["changes"]]) == (
        200, "kid/f", False, ["добавлено задание eve/regex:1 в блок «Git»"])
    assert pool.call("GET", f"{path}/merges", "max")[1]["merges"] == []
    assert pool.call("POST", f"{path}/merges/{mid}", "kid", {"action": "merge"})[0] == 403
    assert pool.call("POST", f"{path}/merges/{mid}", "bob", {"action": "merge"})[0] == 200
    view = pool.call("GET", path, "bob")[1]
    assert (_tasks(view), view["history"][0]["what"]) == (["bob/git-init:1", "eve/regex:1"],
                                                          "слияние из kid/f от kid")
    assert pool.call("GET", f"{fork}/sync", "kid")[1]["behind"] == 0       # the fork is level again


@pytest.mark.tier1
def test_merge_needs_a_pulled_fork(pool: _Courses) -> None:
    path, fork = _fork(pool)
    pool.call("PUT", path, "bob", {"auto_update": False})
    code, body = pool.call("POST", f"{fork}/merge", "kid", {})
    assert (code, body["error"]) == (409, "сначала подтяните изменения исходного курса")
    assert pool.call("POST", f"{fork}/merge", "max", {})[0] == 403


@pytest.mark.tier1
def test_stale_merge_refused_then_refreshed(pool: _Courses) -> None:
    path, fork, mid = _offered(pool)
    pool.call("PUT", path, "bob", {"auto_update": False})
    assert pool.call("GET", f"{path}/merges", "bob")[1]["merges"][0]["stale"] is True
    code, body = pool.call("POST", f"{path}/merges/{mid}", "bob", {"action": "merge"})
    assert (code, body["error"]) == (409, "запрос устарел — автору нужно подтянуть изменения и обновить его")
    pool.call("POST", f"{fork}/sync", "kid", {})
    assert pool.call("POST", f"{fork}/merge", "kid", {})[1]["merge"]["id"] == mid
    assert pool.call("POST", f"{path}/merges/{mid}", "bob", {"action": "merge"})[0] == 200


@pytest.mark.tier1
def test_private_image_blocks_merge_into_public(pool: _Courses) -> None:
    _path, fork = _fork(pool)
    pool.call("PUT", fork, "kid", {"visibility": "private"})
    with RepoIndex(pool.r.store.root / ".repos", "eve/regex").locked() as idx:
        idx.set_meta(visibility="private")
    pool.call("PUT", "/courses/kid/f/members/eve", "kid", {"role": "author"})
    block = pool.call("GET", fork, "kid")[1]["blocks"][0]["id"]
    assert pool.call("POST", f"{fork}/tasks", "eve", {"repo": "eve/regex", "tag": "1", "block_id": block})[0] == 201
    code, body = pool.call("POST", f"{fork}/merge", "kid", {})
    assert (code, body["error"]) == (409, ("eve/regex приватный — в публичный курс его не поставить; "
                                           "сделайте образ публичным"))


@pytest.mark.tier1
def test_accept_reaches_parent_mirrors(pool: _Courses) -> None:
    path, _fork_path, mid = _offered(pool)
    pool.call("POST", f"{path}/mirror", "max", {"name": "m"})
    pool.call("POST", f"{path}/merges/{mid}", "bob", {"action": "merge"})
    assert _tasks(pool.call("GET", "/courses/max/m", "max")[1]) == ["bob/git-init:1", "eve/regex:1"]


@pytest.mark.tier1
def test_reject_and_withdraw(pool: _Courses) -> None:
    path, fork, mid = _offered(pool)
    assert pool.call("POST", f"{path}/merges/{mid}", "bob", {"action": "withdraw"})[0] == 403
    code, body = pool.call("POST", f"{path}/merges/{mid}", "bob", {"action": "reject", "reason": "позже"})
    assert (code, body["merge"]["state"], body["merge"]["reason"]) == (200, "rejected", "позже")
    assert pool.call("GET", f"{path}/merges", "kid")[1]["merges"][0]["state"] == "rejected"
    mid2 = pool.call("POST", f"{fork}/merge", "kid", {})[1]["merge"]["id"]
    assert pool.call("POST", f"{path}/merges/{mid2}", "kid", {"action": "withdraw"})[0] == 200


@pytest.mark.tier1
def test_merge_removing_solved_task_keeps_progress(pool: _Courses) -> None:
    path, fork = _fork(pool)
    digest = RepoIndex(pool.r.store.root / ".repos", "bob/git-init").get("1", 2).task_digest
    assert pool.call("POST", "/submit", "max", {"task_ref": "bob/git-init:1", "course": "bob/linux",
                                                "digest": digest, "passed": True})[1]["status"] == "passed"
    pool.call("DELETE", f"{fork}/tasks/bob/git-init:1", "kid")
    mid = pool.call("POST", f"{fork}/merge", "kid", {})[1]["merge"]["id"]
    assert pool.call("POST", f"{path}/merges/{mid}", "bob", {"action": "merge"})[0] == 200
    assert _tasks(pool.call("GET", path, "bob")[1]) == []
    assert pool.call("GET", "/progress", "max")[1]["progress"]["max"]["bob/git-init:1"]["status"] == "passed"
