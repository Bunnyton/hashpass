"""Tier1: copies of a course -- the copyable structure, diff and three-way merge (spec 2026-10-31)."""
from pathlib import Path

import pytest

from hashpass.registry import course_copies as cc
from hashpass.registry import courses as c
from hashpass.registry.courses import Course, CourseStore


@pytest.fixture
def store(tmp_path: Path) -> CourseStore:
    return CourseStore(tmp_path / "courses")


def _task(repo: str, n: int = 1, **kw: object) -> dict:
    return {"repo": repo, "tag": "1", "n": n, "pinned": False, "hidden": False, "added_by": "bob"} | kw


@pytest.mark.tier1
def test_old_course_reads_with_defaults() -> None:
    course = Course.from_raw({"id": "c-1", "owner": "a", "name": "x"})
    assert course.origin == {}
    assert course.allow_mirrors is True
    assert course.allow_forks is False
    assert course.merges == []
    assert course.kind == ""


@pytest.mark.tier1
def test_kind_of_copies() -> None:
    assert Course.from_raw({"id": "c", "owner": "a", "name": "x", "origin": {"kind": "mirror"}}).kind == "mirror"
    assert Course.from_raw({"id": "c", "owner": "a", "name": "x", "origin": {"kind": "fork"}}).kind == "fork"
    gone = Course.from_raw({"id": "c", "owner": "a", "name": "x", "origin": {"kind": "mirror", "gone": True}})
    assert gone.kind == "fork"                       # a mirror whose parent is gone is one's own to edit


@pytest.mark.tier1
def test_structure_skips_hidden_and_open() -> None:
    course = Course(id="c", owner="bob", name="linux", auto_update=False)
    course.blocks = [{"id": "b1", "name": "Git", "open": False,
                      "tasks": [_task("bob/a"), _task("bob/b", hidden=True)]}]
    assert cc.structure(course) == {
        "auto_update": False,
        "blocks": [{"id": "b1", "name": "Git",
                    "tasks": [{"repo": "bob/a", "tag": "1", "n": 1, "pinned": False, "added_by": "bob"}]}]}


@pytest.mark.tier1
def test_apply_structure_keeps_own_open_and_hidden() -> None:
    mirror = Course(id="m", owner="kid", name="m")
    mirror.blocks = [{"id": "b1", "name": "Git", "open": False,
                      "tasks": [_task("bob/a"), _task("kid/h", hidden=True)]}]
    struct = {"auto_update": True,
              "blocks": [{"id": "b1", "name": "Гит", "tasks": [cc.structure_task(_task("bob/a", 2))]},
                         {"id": "b2", "name": "Regex", "tasks": [cc.structure_task(_task("bob/r"))]}]}
    cc.apply_structure(mirror, struct, source_open={"b1": True, "b2": True})
    b1, b2 = mirror.blocks
    assert (b1["name"], b1["open"]) == ("Гит", False)
    assert [(t["repo"], t["n"], t["hidden"]) for t in b1["tasks"]] == [("bob/a", 2, False), ("kid/h", 1, True)]
    assert (b2["name"], b2["open"], [t["repo"] for t in b2["tasks"]]) == ("Regex", True, ["bob/r"])
    assert cc.structure(mirror) == struct


@pytest.mark.tier1
def test_apply_structure_hidden_of_a_gone_block_moves_to_last(store: CourseStore) -> None:
    course = store.create("kid", "m")
    with store.edit(course.ref) as cur:
        b = c.add_block(cur, "Old")
        c.add_task(cur, "kid/h", "1", 1, b, by="kid")["hidden"] = True
    course = store.get(course.ref)
    cc.apply_structure(course, {"auto_update": True, "blocks": [{"id": "b9", "name": "New", "tasks": []}]})
    assert [(b["id"], [t["repo"] for t in b["tasks"]]) for b in course.blocks] == [("b9", ["kid/h"])]


@pytest.mark.tier1
def test_block_open() -> None:
    course = Course(id="c", owner="bob", name="x")
    course.blocks = [{"id": "b1", "name": "A", "open": False, "tasks": []}, {"id": "b2", "name": "B", "tasks": []}]
    assert cc.block_open(course) == {"b1": False, "b2": True}
