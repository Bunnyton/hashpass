"""
Tier1: blocks and tasks may wait for particular tasks (no version), not only for blocks.

User 2026-11-05: «зависимости не только между блоками, но и между заданиями — конкретное задание
(без версии) если выполнилось, открывается другое или даже целый блок».
"""
from pathlib import Path

import pytest

from hashpass.registry import courses as c
from hashpass.registry.courses import CourseStore


@pytest.fixture
def course(tmp_path: Path) -> c.Course:
    course = CourseStore(tmp_path / "courses").create("bob", "linux")
    for name, repos in (("Git", ["bob/a", "bob/b"]), ("Regex", ["bob/c"]), ("Приз", ["bob/x"])):
        block = c.add_block(course, name)
        for repo in repos:
            c.add_task(course, repo, "1", 1, block, by="bob")
    return course


def _ids(course: c.Course) -> list[str]:
    return [b["id"] for b in course.blocks]


def _task(course: c.Course, repo: str) -> tuple[dict, dict]:
    return next((b, t) for b, t in course.tasks() if t["repo"] == repo)


@pytest.mark.tier1
def test_a_block_opens_once_a_particular_task_is_solved(course: c.Course) -> None:
    prize = _ids(course)[2]
    c.set_block_needs(course, prize, ["bob/c:1"])
    block = course.blocks[2]
    assert block["needs"] == ["bob/c:1"]
    assert c.waiting_for(course, block, set()) == ["c"]
    assert c.waiting_for(course, block, {"bob/c:1"}) == []


@pytest.mark.tier1
def test_a_task_waits_for_tasks_and_blocks_and_for_its_own_block(course: c.Course) -> None:
    git, regex, prize = _ids(course)
    c.set_task_needs(course, "bob/b", "1", ["bob/a:1"])
    block, task = _task(course, "bob/b")
    assert c.task_waiting(course, block, task, set()) == ["a"]
    assert c.task_waiting(course, block, task, {"bob/a:1"}) == []
    c.set_task_needs(course, "bob/x", "1", [regex])
    c.set_block_needs(course, prize, [git])
    block, task = _task(course, "bob/x")
    assert c.task_waiting(course, block, task, set()) == ["Git", "Regex"]          # its block's first
    assert c.task_waiting(course, block, task, {"bob/a:1", "bob/b:1", "bob/c:1"}) == []
    c.set_task_needs(course, "bob/x", "1", [])
    assert "needs" not in _task(course, "bob/x")[1]


@pytest.mark.tier1
def test_waiting_for_each_other_and_unknown_tasks_are_refused(course: c.Course) -> None:
    git, _regex, _prize = _ids(course)
    with pytest.raises(ValueError, match="такого задания"):
        c.set_task_needs(course, "bob/x", "1", ["bob/nope:1"])
    with pytest.raises(ValueError, match="сам"):
        c.set_task_needs(course, "bob/x", "1", ["bob/x:1"])
    c.set_block_needs(course, git, ["bob/x:1"])
    with pytest.raises(ValueError, match="ждут друг друга"):
        c.set_task_needs(course, "bob/x", "1", ["bob/a:1"])                       # a is in Git
    with pytest.raises(ValueError, match="ждут друг друга"):
        c.set_task_needs(course, "bob/x", "1", [git])


@pytest.mark.tier1
def test_a_removed_task_leaves_no_condition_behind(course: c.Course) -> None:
    prize = _ids(course)[2]
    c.set_block_needs(course, prize, ["bob/c:1"])
    c.set_task_needs(course, "bob/x", "1", ["bob/a:1"])
    c.remove_task(course, "bob/c", "1")
    c.remove_task(course, "bob/a", "1")
    assert "needs" not in course.blocks[2] and "needs" not in _task(course, "bob/x")[1]
