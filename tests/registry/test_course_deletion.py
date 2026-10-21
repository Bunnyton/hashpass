"""Tier1: deleting a revision someone else's course uses (spec 2026-10-21 §2.7)."""
from pathlib import Path

import pytest

from tests.registry.test_course_api import _Courses


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("eve/regex", "1", image="r1", task="t1", user="eve")
    p.push("eve/regex", "1", image="r2", task="t2", user="eve")
    for name, pinned in (("pinned", True), ("follows", False)):
        p.call("POST", "/courses", "bob", {"name": name})
        p.call("POST", f"/courses/bob/{name}/tasks", "bob", {"repo": "eve/regex", "tag": "1", "n": 2})
        if pinned:
            p.call("PUT", f"/courses/bob/{name}/tasks/eve/regex:1", "bob", {"pinned": True})
    return p


def _task(pool: _Courses, course: str) -> list[dict]:
    return [t for b in pool.call("GET", f"/courses/bob/{course}", "bob")[1]["blocks"] for t in b["tasks"]]


@pytest.mark.tier1
def test_in_someone_elses_course_it_waits_for_the_admin(pool: _Courses) -> None:
    code, body = pool.call("DELETE", "/revisions/eve/regex/1/2", "eve")
    assert code == 202  # noqa: PLR2004
    assert sorted(body["courses"]) == ["bob/follows", "bob/pinned"]
    assert pool.r.store.exists("eve/regex:1_v2")
    rid = body["request"]
    assert pool.call("POST", f"/deletion-requests/{rid}", "eve", {"action": "approve"})[0] == 403  # noqa: PLR2004
    assert pool.call("POST", f"/deletion-requests/{rid}", "bunnyton", {"action": "approve"})[0] == 200  # noqa: PLR2004
    assert not pool.r.store.exists("eve/regex:1_v2")
    assert [t["revision"] for t in _task(pool, "follows")] == ["eve/regex:1_v1"]   # falls back
    assert _task(pool, "pinned") == []                                            # removed ...
    props = pool.call("GET", "/courses/bob/pinned", "bob")[1]["proposals"]
    assert [(p["kind"], p["n"], p["state"]) for p in props] == [("restore", 1, "open")]  # ... restore offered


@pytest.mark.tier1
def test_the_owner_may_withdraw_the_request(pool: _Courses) -> None:
    rid = pool.call("DELETE", "/revisions/eve/regex/1/2", "eve")[1]["request"]
    assert [r["id"] for r in pool.call("GET", "/deletion-requests", "eve")[1]["requests"]] == [rid]
    assert pool.call("POST", f"/deletion-requests/{rid}", "eve", {"action": "withdraw"})[0] == 200  # noqa: PLR2004
    assert pool.call("GET", "/deletion-requests", "bunnyton")[1]["requests"] == []
    assert pool.r.store.exists("eve/regex:1_v2")


@pytest.mark.tier1
def test_unused_revision_goes_at_once(pool: _Courses) -> None:
    assert pool.call("DELETE", "/revisions/eve/regex/1/1", "eve")[0] == 200  # noqa: PLR2004
    assert not pool.r.store.exists("eve/regex:1_v1")


@pytest.mark.tier1
def test_private_course_names_are_not_shown(pool: _Courses) -> None:
    pool.call("POST", "/courses", "max", {"name": "secret", "visibility": "private"})
    pool.call("POST", "/courses/max/secret/tasks", "max", {"repo": "eve/regex", "tag": "1", "n": 2})
    body = pool.call("DELETE", "/revisions/eve/regex/1/2", "eve")[1]
    assert "max/secret" not in body["courses"]
    assert "ещё приватных курсов: 1" in body["courses"]
