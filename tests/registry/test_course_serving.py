"""Tier1: tasks reach students through courses -- the course's revision, credit, progress (spec §8, §9)."""
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from hashpass.registry.revisions import RepoIndex
from tests.registry.test_course_api import _Courses


def _get(url: str, token: str | None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers)


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/git-init", "1", image="one", task="t1")
    p.push("bob/git-init", "1", image="two", task="t2")
    p.call("POST", "/courses", "bob", {"name": "linux", "visibility": "private"})
    block = p.call("POST", "/courses/bob/linux/blocks", "bob", {"name": "Git"})[1]["id"]
    p.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": "bob/git-init", "tag": "1", "n": 1,
                                                       "block_id": block})
    p.call("PUT", "/courses/bob/linux/tasks/bob/git-init:1", "bob", {"pinned": True})
    invite = p.call("GET", "/courses/bob/linux", "bob")[1]["invite"]
    p.call("POST", "/courses/bob/linux/join", "kid", {"invite": invite})
    return p


def _digest(pool: _Courses, n: int) -> str:
    return RepoIndex(pool.r.store.root / ".repos", "bob/git-init").get("1", n).task_digest


@pytest.mark.tier1
def test_a_member_gets_the_courses_revision(pool: _Courses) -> None:
    code, headers = _get(f"{pool.url}/task/bob/git-init/1?course=bob/linux", pool.tok["kid"])
    assert (code, headers["X-Image-Ref"]) == (200, "bob/git-init:1_v1")       # pinned to v1
    # user 2026-10-23 («искать по образам всем … и их выполнять»): a public task, any version,
    # to anyone -- run outside the course; the course's credit still needs the course's version
    assert _get(f"{pool.url}/task/bob/git-init/1_v2", pool.tok["kid"])[0] == 200  # noqa: PLR2004
    assert _get(f"{pool.url}/task/bob/git-init/1", pool.tok["max"])[0] == 200     # not a member  # noqa: PLR2004


@pytest.mark.tier1
def test_credit_comes_from_the_course_and_records_it(pool: _Courses) -> None:
    code, body = pool.call("POST", "/submit", "kid", {"task_ref": "bob/git-init:1", "course": "bob/linux",
                                                      "digest": _digest(pool, 2), "passed": True})
    assert (code, body["status"]) == (200, "failed")                          # not the course's revision
    code, body = pool.call("POST", "/submit", "kid", {"task_ref": "bob/git-init:1", "course": "bob/linux",
                                                      "digest": _digest(pool, 1), "passed": True})
    assert (code, body["status"]) == (200, "passed")
    rec = pool.call("GET", "/progress", "kid")[1]["progress"]["kid"]["bob/git-init:1"]
    assert (rec["course"], rec["n"]) == ("bob/linux", 1)
    assert pool.call("POST", "/submit", "max", {"task_ref": "bob/git-init:1", "course": "bob/linux",
                                                "digest": _digest(pool, 1), "passed": True})[1]["status"] \
        == "unavailable"


@pytest.mark.tier1
def test_course_staff_do_not_see_their_students(pool: _Courses) -> None:
    """User 2026-10-25: who takes a course and how far -- the admin only."""
    pool.call("POST", "/submit", "kid", {"task_ref": "bob/git-init:1", "course": "bob/linux",
                                         "digest": _digest(pool, 1), "passed": True})
    pool.r.users.set_role("bob", "user")                           # not a legacy author any more
    assert set(pool.call("GET", "/progress", "bob")[1]["progress"]) == {"bob"}
    assert "bob/git-init:1" in pool.call("GET", "/progress", "bunnyton")[1]["progress"]["kid"]
    assert pool.call("GET", "/progress", "max")[1]["progress"] == {"max": {}}


@pytest.mark.tier1
def test_attempts_in_a_course_need_membership(pool: _Courses) -> None:
    body = {"task_ref": "bob/git-init:1", "course": "bob/linux", "session_id": "0123456789abcdef0123456789abcdef", "seq": 0,
            "entries": [{"command": "git init", "output": ""}]}
    assert pool.call("POST", "/attempt", "kid", body)[0] == 200  # noqa: PLR2004
    assert pool.call("POST", "/attempt", "max", body)[0] == 404  # noqa: PLR2004
