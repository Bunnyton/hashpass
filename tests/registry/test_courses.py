"""Tier1: the course model -- blocks, tasks pinned to revisions, proposals, members, requests (spec §4-§6)."""
from pathlib import Path

import pytest

from hashpass.registry import courses as c
from hashpass.registry.courses import CourseConflictError, CourseStore


@pytest.fixture
def store(tmp_path: Path) -> CourseStore:
    return CourseStore(tmp_path / "courses")


@pytest.mark.tier1
def test_create_get_and_names(store: CourseStore) -> None:
    course = store.create("bob", "linux", title="Linux")
    assert (course.ref, course.visibility, course.auto_update, course.auto_accept) == (
        "bob/linux", "public", True, False)
    assert course.invite
    assert store.get("bob/linux").title == "Linux"
    with pytest.raises(ValueError, match="уже есть"):
        store.create("bob", "linux")
    with pytest.raises(ValueError, match="имя курса"):
        store.create("bob", "Bad Name")
    assert store.create("eve", "linux").ref == "eve/linux"        # unique per owner only


@pytest.mark.tier1
def test_edit_bumps_rev_and_detects_conflicts(store: CourseStore) -> None:
    store.create("bob", "linux")
    with store.edit("bob/linux") as course:
        course.title = "Linux 2"
    assert store.get("bob/linux").rev == 1
    with pytest.raises(CourseConflictError), store.edit("bob/linux", expect_rev=0) as course:
        course.title = "stale"
    assert store.get("bob/linux").title == "Linux 2"


@pytest.mark.tier1
def test_roles(store: CourseStore) -> None:
    course = store.create("bob", "linux")
    course.members = {"ann": "author", "max": "maintainer", "kid": "member"}
    assert [course.role_of(u) for u in ("bob", "max", "ann", "kid", "eve", None)] == [
        "owner", "maintainer", "author", "member", None, None]


@pytest.mark.tier1
def test_blocks_and_tasks(store: CourseStore) -> None:
    course = store.create("bob", "linux")
    git = c.add_block(course, "Git")
    docker = c.add_block(course, "Docker")
    c.add_task(course, "bob/git-init", "1", 3, git, by="bob")
    c.add_task(course, "bob/git-log", "1", 1, git, by="bob")
    with pytest.raises(ValueError, match="уже в курсе"):
        c.add_task(course, "bob/git-init", "1", 4, docker, by="bob")
    with pytest.raises(ValueError, match="пуст"):
        c.remove_block(course, git)
    c.move_task(course, "bob/git-log", "1", -1)
    assert [t["repo"] for t in course.blocks[0]["tasks"]] == ["bob/git-log", "bob/git-init"]
    c.remove_block(course, docker)
    assert [b["name"] for b in course.blocks] == ["Git"]
    assert course.find_task("bob/git-init", "1")["n"] == 3  # noqa: PLR2004


@pytest.mark.tier1
def test_effective_revision_follows_latest_unless_pinned(store: CourseStore) -> None:
    course = store.create("bob", "linux")
    block = c.add_block(course, "Git")
    task = c.add_task(course, "bob/git-init", "1", 2, block, by="bob")
    assert c.effective_n(course, task, latest=5) == 5  # noqa: PLR2004
    task["pinned"] = True
    assert c.effective_n(course, task, latest=5) == 2  # noqa: PLR2004
    task["pinned"] = False
    course.auto_update = False
    assert c.effective_n(course, task, latest=5) == 2  # noqa: PLR2004
    assert c.pending_updates(course, lambda _r, _t: 5) == [("bob/git-init", "1", 5)]


@pytest.mark.tier1
def test_proposal_lifecycle(store: CourseStore) -> None:
    course = store.create("bob", "linux")
    block = c.add_block(course, "Git")
    prop = c.propose(course, "add", "eve/regex", "1", 2, block, by="eve", comment="хорошее", now=10.0)
    again = c.propose(course, "add", "eve/regex", "1", 3, block, by="eve", comment="свежее", now=11.0)
    assert again["id"] == prop["id"]                         # one open proposal per tag
    assert (again["n"], again["comment"]) == (3, "свежее")
    c.decide(course, prop["id"], accept=True, by="bob", now=12.0)
    assert course.find_task("eve/regex", "1")["n"] == 3  # noqa: PLR2004
    assert course.proposals[0]["state"] == "accepted"
    upd = c.propose(course, "update", "eve/regex", "1", 4, block, by="eve", comment="", now=13.0)
    c.decide(course, upd["id"], accept=False, by="bob", reason="сыро", now=14.0)
    assert course.find_task("eve/regex", "1")["n"] == 3  # noqa: PLR2004
    assert course.proposals[-1]["reason"] == "сыро"
    third = c.propose(course, "update", "eve/regex", "1", 5, block, by="eve", comment="", now=15.0)
    with pytest.raises(PermissionError):
        c.withdraw(course, third["id"], by="bob")
    c.withdraw(course, third["id"], by="eve")
    assert third["state"] == "withdrawn"


@pytest.mark.tier1
def test_auto_accept_takes_proposals_at_once(store: CourseStore) -> None:
    course = store.create("bob", "linux")
    course.auto_accept = True
    block = c.add_block(course, "Git")
    prop = c.propose(course, "add", "eve/regex", "1", 1, block, by="eve", comment="", now=1.0)
    assert prop["state"] == "accepted"
    assert course.find_task("eve/regex", "1") is not None


@pytest.mark.tier1
def test_restore_proposal_puts_the_task_back(store: CourseStore) -> None:
    course = store.create("bob", "linux")
    block = c.add_block(course, "Git")
    c.add_task(course, "eve/regex", "1", 3, block, by="bob")
    c.remove_task(course, "eve/regex", "1")
    prop = c.propose(course, "restore", "eve/regex", "1", 2, block, by="eve", comment="", now=1.0)
    c.decide(course, prop["id"], accept=True, by="bob", now=2.0)
    assert course.find_task("eve/regex", "1")["n"] == 2  # noqa: PLR2004


@pytest.mark.tier1
def test_access_requests_and_invites(store: CourseStore) -> None:
    course = store.create("bob", "linux", visibility="private")
    c.request_access(course, "eve", "пустите", now=0.0)
    with pytest.raises(ValueError, match="уже"):
        c.request_access(course, "eve", "ну пустите", now=1.0)
    c.decide_request(course, "eve", accept=False, by="bob", now=2.0)
    with pytest.raises(ValueError, match="сутки"):
        c.request_access(course, "eve", "ещё раз", now=3.0)
    c.request_access(course, "eve", "прошли сутки", now=2.0 + 86400)
    c.decide_request(course, "eve", accept=True, by="bob", now=86500.0)
    assert course.role_of("eve") == "member"
    assert not c.join_by_invite(course, "kid", "wrong")
    assert c.join_by_invite(course, "kid", course.invite)
    old = course.invite
    c.rotate_invite(course)
    assert course.invite != old
    assert not c.join_by_invite(course, "max", old)


@pytest.mark.tier1
def test_courses_with_a_tag(store: CourseStore) -> None:
    for name in ("one", "two"):
        store.create("bob", name)
        with store.edit(f"bob/{name}") as course:
            c.add_task(course, "eve/regex", "1", 1, c.add_block(course, "B"), by="bob")
    store.create("bob", "three")
    assert sorted(x.ref for x in store.courses_with("eve/regex", "1")) == ["bob/one", "bob/two"]
