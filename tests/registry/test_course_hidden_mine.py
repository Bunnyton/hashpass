"""Tier1: a course's hidden tasks for the people given the right; one's own tasks and their status (2026-10-26)."""
from pathlib import Path

import pytest

from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page

PATH = "/courses/bob/linux"


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/git-init", "1", image="one", task="t1")
    p.push("bob/hidden", "1", image="h", task="h1")
    p.push("ann/mine", "1", image="m", task="m1", user="ann")
    p.push("eve/regex", "1", image="re", task="r1", user="eve")
    p.call("POST", "/courses", "bob", {"name": "linux"})
    block = p.call("POST", f"{PATH}/blocks", "bob", {"name": "Git"})[1]["id"]
    closed = p.call("POST", f"{PATH}/blocks", "bob", {"name": "Потом"})[1]["id"]
    p.call("PUT", f"{PATH}/blocks/{closed}", "bob", {"open": False})
    for repo, where in (("bob/git-init", block), ("bob/hidden", block)):
        p.call("POST", f"{PATH}/tasks", "bob", {"repo": repo, "tag": "1", "block_id": where})
    p.call("PUT", f"{PATH}/tasks/bob/hidden:1", "bob", {"hidden": True})
    p.call("PUT", f"{PATH}/members/ann", "bob", {"role": "author"})
    p.call("POST", f"{PATH}/tasks", "ann", {"repo": "ann/mine", "tag": "1", "block_id": closed})
    p.p_block = block
    return p


def _refs(view: dict) -> list[str]:
    return [t["ref"] for b in view["blocks"] for t in b["tasks"]]


def _catalog(pool: _Courses, user: str) -> dict[str, dict]:
    code, body = pool.call("GET", "/catalog?course=bob/linux", user)
    assert code == 200, body  # noqa: PLR2004
    return {r["ref"]: r for r in body["catalog"]}


@pytest.mark.tier1
def test_an_author_sees_its_own_hidden_task_not_others(pool: _Courses) -> None:
    assert _refs(pool.call("GET", PATH, "ann")[1]) == ["bob/git-init:1", "ann/mine:1"]
    rows = _catalog(pool, "ann")
    assert "bob/hidden:1" not in rows
    assert rows["ann/mine:1"]["preview"] and rows["ann/mine:1"]["mine"]


@pytest.mark.tier1
def test_people_box_gives_an_author_the_hidden_tasks(pool: _Courses) -> None:
    assert pool.call("PUT", f"{PATH}/members/ann", "kid", {"extras": ["hidden"]})[0] == 403  # noqa: PLR2004
    code, body = pool.call("PUT", f"{PATH}/members/ann", "bob", {"extras": ["hidden"]})
    assert (code, body["extras"], body["role"]) == (200, ["hidden"], "author")
    view = pool.call("GET", PATH, "ann")[1]
    assert _refs(view) == ["bob/git-init:1", "bob/hidden:1", "ann/mine:1"]
    assert view["extras"] == {"ann": ["hidden"]}
    rows = _catalog(pool, "ann")
    assert rows["bob/hidden:1"]["preview"] and not rows["bob/hidden:1"]["available"]
    assert "скрытые задания" in view["history"][0]["what"]
    pool.call("PUT", f"{PATH}/members/ann", "bob", {"extras": []})
    assert "bob/hidden:1" not in _catalog(pool, "ann")


@pytest.mark.tier1
def test_an_author_given_progress_sees_the_courses_people(pool: _Courses) -> None:
    pool.call("POST", f"{PATH}/join", "kid")
    assert "students" not in _web(pool, "ann")
    pool.call("PUT", f"{PATH}/members/ann", "bob", {"role": "author", "extras": ["progress", "hidden"]})
    assert pool.call("GET", PATH, "bob")[1]["extras"] == {"ann": ["hidden", "progress"]}
    page = _web(pool, "ann")
    assert "id='students'" in page and "Участники курса" in page and "kid" in page


@pytest.mark.tier1
def test_extras_need_the_givers_own_boxes(pool: _Courses) -> None:
    pool.call("PUT", f"{PATH}/members/max", "bob", {"role": "admin", "perms": ["people"]})
    assert pool.call("PUT", f"{PATH}/members/ann", "max", {"extras": ["progress"]})[0] == 403  # noqa: PLR2004
    pool.call("PUT", f"{PATH}/members/ann", "bob", {"extras": ["progress"]})
    # max (people only) can neither take ann's progress nor unmake her author
    assert pool.call("PUT", f"{PATH}/members/ann", "max", {"role": "member"})[0] == 403  # noqa: PLR2004
    assert pool.call("PUT", f"{PATH}/members/ann", "max", {"extras": []})[0] == 200  # noqa: PLR2004
    assert pool.call("GET", PATH, "bob")[1]["extras"] == {"ann": ["progress"]}       # kept


@pytest.mark.tier1
def test_the_extras_go_with_the_author_role(pool: _Courses) -> None:
    pool.call("PUT", f"{PATH}/members/ann", "bob", {"extras": ["hidden"]})
    pool.call("PUT", f"{PATH}/members/ann", "bob", {"role": "member"})
    assert pool.call("GET", PATH, "bob")[1]["extras"] == {}
    pool.call("PUT", f"{PATH}/members/ann", "bob", {"role": "author", "extras": ["hidden"]})
    pool.call("DELETE", f"{PATH}/members/ann", "bob")
    assert pool.call("GET", PATH, "bob")[1]["extras"] == {}
    pool.call("PUT", f"{PATH}/members/kid", "bob", {"role": "member"})
    assert pool.call("PUT", f"{PATH}/members/kid", "bob", {"extras": ["hidden"]})[0] == 400  # noqa: PLR2004


def _web(pool: _Courses, user: str) -> str:
    return _page(_browser(pool, user), f"{pool.url}/c/bob/linux")[1]


@pytest.mark.tier1
def test_a_proposer_sees_its_proposals_and_their_status(pool: _Courses) -> None:
    code, body = pool.call("POST", f"{PATH}/tasks", "eve", {"repo": "eve/regex", "tag": "1",
                                                           "block_id": pool.p_block})
    assert code == 201, body  # noqa: PLR2004
    rows = _catalog(pool, "eve")
    mine = rows["eve/regex:1"]
    assert (mine["state"], mine["mine"], mine["block_id"], mine["available"]) == ("pending", True, "proposals", False)
    assert mine["preview"] and mine["digest"]
    assert "eve/regex:1" not in _catalog(pool, "kid")
    pool.call("POST", f"{PATH}/proposals/{body['proposal']['id']}", "bob", {"action": "reject",
                                                                          "reason": "сыро"})
    mine = _catalog(pool, "eve")["eve/regex:1"]
    assert (mine["state"], mine["reason"], mine["rejected"]) == ("rejected", "сыро", True)


@pytest.mark.tier1
def test_an_accepted_proposal_is_a_course_task_marked_mine(pool: _Courses) -> None:
    body = pool.call("POST", f"{PATH}/tasks", "eve", {"repo": "eve/regex", "tag": "1",
                                                     "block_id": pool.p_block})[1]
    pool.call("POST", f"{PATH}/proposals/{body['proposal']['id']}", "bob", {"action": "accept"})
    rows = _catalog(pool, "eve")
    assert rows["eve/regex:1"]["block_id"] == pool.p_block
    assert rows["eve/regex:1"]["mine"] and rows["eve/regex:1"].get("state", "approved") == "approved"
    assert not rows["bob/git-init:1"].get("mine")
