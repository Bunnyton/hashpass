"""
Tier2: holes the whole-branch review of the roles redesign found (spec 2026-10-25).

C1 -- a student read a task's hidden sources and attachments; C2 -- promoting an older user moved
the pool's ownership; C3 -- a `people` admin reset the owner's password or deleted it.
"""
import json
from http import HTTPStatus
from pathlib import Path

import pytest

from hashpass import cli
from hashpass.registry.revisions import RepoIndex
from hashpass.registry.sources import SourceStore
from tests.registry.test_images_web import _req, _seed
from tests.registry.test_pool_perms_gates import _PW, _admin, _cookie


def _hidden_task(registry, tmp_path: Path) -> None:
    _seed(registry, "boss/lab:1", tmp_path, task=True)
    tdir = tmp_path / "lab-src"
    (tdir / "hp").mkdir(parents=True)
    (tdir / "Taskfile").write_text("stage\n", encoding="utf-8")
    (tdir / "hp" / "solve").write_text("SECRET-ANSWER\n", encoding="utf-8")
    SourceStore(Path(registry.store.root) / "sources").put_archive("boss/lab:1", cli.pack_task_source(tdir))
    with RepoIndex(Path(registry.store.root) / ".repos", "boss/lab").locked() as idx:
        idx.set_meta(visibility="private", hide_sources=True)


@pytest.mark.tier2
def test_a_student_reads_no_hidden_sources(registry, tmp_path) -> None:
    _hidden_task(registry, tmp_path)
    registry.users.add("stud", _PW)
    opener, cookie = _cookie(registry, "stud")
    base = registry.base_url
    status, _, body = _req(opener, "GET", f"{base}/web/images/source?ref=boss%2Flab%3A1&path=hp%2Fsolve&raw=1",
                           cookie=cookie)
    assert status != HTTPStatus.OK and "SECRET-ANSWER" not in body
    status, _, _ = _req(opener, "GET", f"{base}/web/images/source-archive?ref=boss%2Flab%3A1", cookie=cookie)
    assert status != HTTPStatus.OK
    status, _, _ = _req(opener, "GET", f"{base}/web/images/file?ref=boss%2Flab%3A1&name=x.txt", cookie=cookie)
    assert status in (HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND)
    registry.users.add("boss", _PW)                              # its owner still reads them
    opener, cookie = _cookie(registry, "boss")
    status, _, body = _req(opener, "GET", f"{base}/web/images/source?ref=boss%2Flab%3A1&path=hp%2Fsolve&raw=1",
                           cookie=cookie)
    assert status == HTTPStatus.OK and "SECRET-ANSWER" in body


@pytest.mark.tier2
def test_promoting_an_older_user_does_not_move_the_ownership(registry, monkeypatch) -> None:
    monkeypatch.setenv("HASHPASS_ADMIN", "nobody-here")
    registry.users.add("old", _PW)                               # registered before the admins
    path = registry.users._path                                  # noqa: SLF001
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["old"]["created_at"] = 1.0
    path.write_text(json.dumps(raw), encoding="utf-8")
    registry.users.add("boss", _PW, role="admin")                # the owner: the only admin, first
    opener, cookie = _cookie(registry, "boss")
    _req(opener, "GET", f"{registry.base_url}/web/users", cookie=cookie)   # the owner is settled
    registry.users.add("b", _PW, role="admin")
    registry.users.set_perms("b", ["admins"])
    opener, cookie = _cookie(registry, "b")
    _req(opener, "POST", f"{registry.base_url}/web/users/role", cookie=cookie, data={"user": "old", "role": "admin"})
    opener, cookie = _cookie(registry, "boss")
    page = _req(opener, "GET", f"{registry.base_url}/web/users", cookie=cookie)[2]
    assert "name='perms'" in page                                # boss still holds `admins`


@pytest.mark.tier2
@pytest.mark.parametrize("route", ["reset", "delete"])
def test_a_people_admin_does_not_touch_the_owner(registry, route: str) -> None:
    opener, cookie = _admin(registry, "clerk", ["people"])      # `admin` is the owner
    _req(opener, "POST", f"{registry.base_url}/web/users/{route}", cookie=cookie, data={"user": "admin"})
    assert registry.users.has("admin")
    _status, _, body = _req(opener, "POST", f"{registry.base_url}/web/users/reset", cookie=cookie,
                           data={"user": "admin"})
    assert "token=" not in body


# -- the course side and the rest (I1-I4, M2) -------------------------------------------------

from tests.registry.test_course_api import _course, _Courses  # noqa: E402
from tests.registry.test_course_api import pool as pool  # noqa: E402, PLC0414  (the fixture)


@pytest.mark.tier1
def test_a_course_admin_does_not_strip_boxes_it_lacks(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("PUT", f"{path}/members/ann", "bob", {"role": "admin", "perms": ["admins"]})
    pool.call("PUT", f"{path}/members/max", "bob", {"role": "admin", "perms": ["admins", "content", "people", "progress"]})
    assert pool.call("PUT", f"{path}/members/max", "ann", {"role": "admin", "perms": ["admins"]})[0] == 200  # noqa: PLR2004
    view = pool.call("GET", path, "bob")[1]
    assert view["perms"]["max"] == ["admins", "content", "people", "progress"]   # not ann's to take
    assert pool.call("PUT", f"{path}/members/max", "ann", {"role": "member"})[0] == 403  # noqa: PLR2004
    assert pool.call("DELETE", f"{path}/members/max", "ann")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_an_old_client_keeps_an_admins_boxes(pool: _Courses) -> None:
    path = _course(pool)
    pool.call("PUT", f"{path}/members/ann", "bob", {"role": "admin", "perms": ["admins", "content"]})
    pool.call("PUT", f"{path}/members/max", "bob", {"role": "admin", "perms": ["people"]})
    assert pool.call("PUT", f"{path}/members/max", "bob", {"role": "maintainer"})[0] == 200  # noqa: PLR2004
    assert pool.call("GET", path, "bob")[1]["perms"]["max"] == ["people"]          # kept, not reset
    assert pool.call("PUT", f"{path}/members/kid", "ann", {"role": "maintainer"})[0] == 200  # noqa: PLR2004
    assert pool.call("GET", path, "bob")[1]["perms"]["kid"] == ["content"]         # DEFAULT ∩ ann's


@pytest.mark.tier2
def test_an_admins_only_admin_manages_admins_on_the_web(registry) -> None:
    opener, cookie = _admin(registry, "keeper", ["admins"])
    registry.users.add("kid", _PW)
    status, _, page = _req(opener, "GET", f"{registry.base_url}/web/users", cookie=cookie)
    assert status == HTTPStatus.OK and "Сделать админом" in page
    assert "/web/users/delete" not in page                      # people's controls: not its box
