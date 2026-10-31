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


# -- diff and three-way merge -------------------------------------------------

def _t(repo: str, n: int = 1, pinned: bool = False) -> dict:  # noqa: FBT001, FBT002
    return {"repo": repo, "tag": "1", "n": n, "pinned": pinned, "added_by": "bob"}


def _s(*blocks: tuple, auto_update: bool = True) -> dict:
    """`_s(("b1", "Git", [task, …]), …)` -- a structure."""
    return {"auto_update": auto_update, "blocks": [{"id": i, "name": n, "tasks": list(ts)} for i, n, ts in blocks]}


def _refs(struct: dict) -> list[tuple[str, list[str]]]:
    return [(b["id"], [t["repo"] for t in b["tasks"]]) for b in struct["blocks"]]


A, B, C, X = _t("bob/a"), _t("bob/b"), _t("bob/c"), _t("bob/x")


@pytest.mark.tier1
def test_diff_each_op() -> None:
    base = _s(("b1", "Git", [A, B]), ("b2", "Regex", [C]))
    cases = [
        (_s(("b1", "Git", [A, X, B]), ("b2", "Regex", [C])),
         [{"op": "task_add", "ref": "bob/x:1", "block": "b1", "block_name": "Git", "after": "bob/a:1",
           "task": X}]),
        (_s(("b1", "Git", [A]), ("b2", "Regex", [C])),
         [{"op": "task_remove", "ref": "bob/b:1", "block": "b1"}]),
        (_s(("b1", "Git", [A, _t("bob/b", 3)]), ("b2", "Regex", [C])),
         [{"op": "task_set", "ref": "bob/b:1", "field": "n", "old": 1, "new": 3}]),
        (_s(("b1", "Git", [A, _t("bob/b", pinned=True)]), ("b2", "Regex", [C])),
         [{"op": "task_set", "ref": "bob/b:1", "field": "pinned", "old": False, "new": True}]),
        (_s(("b1", "Git", [B, A]), ("b2", "Regex", [C])),
         [{"op": "task_move", "ref": "bob/b:1", "block": "b1", "block_name": "Git", "after": "^"}]),
        (_s(("b1", "Git", [A]), ("b2", "Regex", [C, B])),
         [{"op": "task_move", "ref": "bob/b:1", "block": "b2", "block_name": "Regex", "after": "bob/c:1"}]),
        (_s(("b1", "Git", [A, B]), ("b2", "Regex", [C]), ("b3", "Vim", [])),
         [{"op": "block_add", "id": "b3", "name": "Vim", "after": "b2"}]),
        (_s(("b1", "Git", [A, B, C])),
         [{"op": "task_move", "ref": "bob/c:1", "block": "b1", "block_name": "Git", "after": "bob/b:1"},
          {"op": "block_remove", "id": "b2", "name": "Regex"}]),
        (_s(("b1", "Гит", [A, B]), ("b2", "Regex", [C])),
         [{"op": "block_rename", "id": "b1", "old": "Git", "new": "Гит"}]),
        (_s(("b2", "Regex", [C]), ("b1", "Git", [A, B])),
         [{"op": "block_move", "id": "b2", "name": "Regex", "after": "^"}]),
        (_s(("b1", "Git", [A, B]), ("b2", "Regex", [C]), auto_update=False),
         [{"op": "auto_update", "old": True, "new": False}]),
    ]
    for new, want in cases:
        assert cc.diff(base, new) == want, want[0]["op"]
    assert cc.diff(base, base) == []


@pytest.mark.tier1
def test_merge3_parent_adds_task_after_neighbour() -> None:
    base = _s(("b1", "Git", [A, B]))
    merged, conflicts = cc.merge3(base, _s(("b1", "Git", [A, B, C])), _s(("b1", "Git", [A, X, B])))
    assert (_refs(merged), conflicts) == ([("b1", ["bob/a", "bob/x", "bob/b", "bob/c"])], [])


@pytest.mark.tier1
def test_merge3_neighbour_missing_goes_to_end() -> None:
    base = _s(("b1", "Git", [A, B]))
    merged, conflicts = cc.merge3(base, _s(("b1", "Git", [B, C])), _s(("b1", "Git", [A, X, B])))
    assert _refs(merged) == [("b1", ["bob/b", "bob/c", "bob/x"])]
    assert [c["op"] for c in conflicts] == []


@pytest.mark.tier1
def test_merge3_new_block_created() -> None:
    base = _s(("b1", "Git", [A]))
    theirs = _s(("b1", "Git", [A]), ("b2", "Regex", [X]))
    merged, _ = cc.merge3(base, _s(("b1", "Git", [A, C])), theirs)
    assert _refs(merged) == [("b1", ["bob/a", "bob/c"]), ("b2", ["bob/x"])]
    assert merged["blocks"][1]["name"] == "Regex"


@pytest.mark.tier1
def test_merge3_both_changed_n_keeps_ours() -> None:
    base = _s(("b1", "Git", [_t("bob/a", 1)]))
    merged, conflicts = cc.merge3(base, _s(("b1", "Git", [_t("bob/a", 3)])), _s(("b1", "Git", [_t("bob/a", 2)])))
    assert merged["blocks"][0]["tasks"][0]["n"] == 3  # noqa: PLR2004
    assert [(c["op"], c["ref"], c["new"]) for c in conflicts] == [("task_set", "bob/a:1", 2)]


@pytest.mark.tier1
def test_merge3_same_change_no_conflict() -> None:
    base = _s(("b1", "Git", [_t("bob/a", 1)]))
    two = _s(("b1", "Git", [_t("bob/a", 2)]))
    merged, conflicts = cc.merge3(base, two, two)
    assert (merged, conflicts) == (two, [])


@pytest.mark.tier1
def test_merge3_parent_removes_task_ours_untouched() -> None:
    base = _s(("b1", "Git", [A, B]))
    merged, conflicts = cc.merge3(base, _s(("b1", "Git", [A, B, C])), _s(("b1", "Git", [A])))
    assert (_refs(merged), conflicts) == ([("b1", ["bob/a", "bob/c"])], [])
    merged, conflicts = cc.merge3(base, _s(("b1", "Git", [A, _t("bob/b", 4)])), _s(("b1", "Git", [A])))
    assert _refs(merged) == [("b1", ["bob/a", "bob/b"])]
    assert [(c["op"], c["ref"]) for c in conflicts] == [("task_remove", "bob/b:1")]


@pytest.mark.tier1
def test_merge3_parent_removes_block_ours_added_into_it() -> None:
    base = _s(("b1", "Git", [A]), ("b2", "Regex", [B]))
    ours = _s(("b1", "Git", [A]), ("b2", "Regex", [B, C]))
    merged, conflicts = cc.merge3(base, ours, _s(("b1", "Git", [A])))
    assert _refs(merged) == [("b1", ["bob/a"]), ("b2", ["bob/c"])]
    assert [c["op"] for c in conflicts] == ["block_remove"]


@pytest.mark.tier1
def test_merge3_hidden_in_parent_is_removed() -> None:
    parent = Course(id="p", owner="bob", name="linux")
    parent.blocks = [{"id": "b1", "name": "Git", "open": True, "tasks": [_task("bob/a"), _task("bob/b")]}]
    base = cc.structure(parent)
    parent.blocks[0]["tasks"][1]["hidden"] = True
    merged, conflicts = cc.merge3(base, base, cc.structure(parent))
    assert (_refs(merged), conflicts) == ([("b1", ["bob/a"])], [])


@pytest.mark.tier1
def test_describe_russian() -> None:
    assert cc.describe({"op": "task_set", "ref": "bob/git-init:1", "field": "n", "old": 2, "new": 3}) == \
        "ревизия bob/git-init:1: v2 → v3"
    assert cc.describe({"op": "task_add", "ref": "bob/x:1", "block": "b1", "block_name": "Git",
                        "after": "^", "task": X}) == "добавлено задание bob/x:1 в блок «Git»"
    for change in cc.diff(_s(("b1", "Git", [A, B]), ("b2", "R", [C])),
                          _s(("b3", "V", [X]), ("b1", "Гит", [_t("bob/b", 2, pinned=True)]), auto_update=False)):
        assert cc.describe(change)


@pytest.mark.tier1
def test_merge3_other_aspect_of_a_task_merges() -> None:
    base = _s(("b1", "Git", [A, B, C]))
    merged, conflicts = cc.merge3(base, _s(("b1", "Git", [B, C, A])), _s(("b1", "Git", [_t("bob/a", 5), B, C])))
    assert _refs(merged) == [("b1", ["bob/b", "bob/c", "bob/a"])]
    assert (merged["blocks"][0]["tasks"][2]["n"], conflicts) == (5, [])


# -- mirrors follow their parent ----------------------------------------------

def _parent_and_mirror(store: CourseStore) -> tuple[str, str]:
    parent = store.create("bob", "linux", title="Linux")
    with store.edit(parent.ref) as cur:
        c.add_task(cur, "bob/a", "1", 1, c.add_block(cur, "Git"), by="bob")
    mirror = store.create_copy(store.get(parent.ref), "kid", "m", "mirror")
    return parent.ref, mirror.ref


@pytest.mark.tier1
def test_parent_change_reaches_mirror(store: CourseStore) -> None:
    parent, mirror = _parent_and_mirror(store)
    with store.edit(parent) as cur:
        c.add_task(cur, "bob/b", "1", 2, cur.blocks[0]["id"], by="bob")
        cur.blocks[0]["tasks"][0]["pinned"] = True
    got = store.get(mirror)
    assert [(t["repo"], t["pinned"]) for _b, t in got.tasks()] == [("bob/a", True), ("bob/b", False)]
    assert got.origin["synced_rev"] == store.get(parent).rev


@pytest.mark.tier1
def test_mirror_keeps_own_block_schedule(store: CourseStore) -> None:
    parent, mirror = _parent_and_mirror(store)
    with store.edit(mirror) as cur:
        cur.blocks[0]["open"] = False
    with store.edit(parent) as cur:
        cur.blocks[0]["name"] = "Гит"
        cur.blocks[0]["open"] = True
    block = store.get(mirror).blocks[0]
    assert (block["name"], block["open"]) == ("Гит", False)


@pytest.mark.tier1
def test_parent_hidden_task_absent_in_mirror(store: CourseStore) -> None:
    parent, mirror = _parent_and_mirror(store)
    with store.edit(parent) as cur:
        cur.blocks[0]["tasks"][0]["hidden"] = True
    assert list(store.get(mirror).tasks()) == []


@pytest.mark.tier1
def test_missed_propagation_caught_on_read(store: CourseStore) -> None:
    parent, mirror = _parent_and_mirror(store)
    raw = store.get(parent)
    c.add_task(raw, "bob/z", "1", 1, raw.blocks[0]["id"], by="bob")
    raw.rev += 1
    store._save(raw)                                  # noqa: SLF001  (a write that skipped edit())
    assert [t["repo"] for _b, t in store.get(mirror).tasks()] == ["bob/a", "bob/z"]


@pytest.mark.tier1
def test_fork_does_not_follow(store: CourseStore) -> None:
    parent = store.create("bob", "linux")
    fork = store.create_copy(parent, "kid", "f", "fork")
    with store.edit(parent.ref) as cur:
        c.add_block(cur, "Git")
    assert store.get(fork.ref).blocks == []


@pytest.mark.tier1
def test_two_parent_writes_mirror_gets_last(store: CourseStore) -> None:
    import threading  # noqa: PLC0415

    parent, mirror = _parent_and_mirror(store)

    def add(repo: str) -> None:
        with store.edit(parent) as cur:
            c.add_task(cur, repo, "1", 1, cur.blocks[0]["id"], by="bob")

    threads = [threading.Thread(target=add, args=(f"bob/t{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    raw = store._read(mirror)                         # noqa: SLF001  (as written, no catch-up)
    assert cc.structure(raw) == cc.structure(store.get(parent))


@pytest.mark.tier1
def test_apply_structure_drops_own_hidden_copy_of_a_task_it_brings() -> None:
    course = Course(id="p", owner="bob", name="x")
    course.blocks = [{"id": "b1", "name": "Git", "open": True, "tasks": [_task("bob/a", hidden=True)]}]
    cc.apply_structure(course, {"auto_update": True,
                                "blocks": [{"id": "b1", "name": "Git", "tasks": [cc.structure_task(_task("bob/a", 2))]}]})
    assert [(t["repo"], t["n"], t["hidden"]) for _b, t in course.tasks()] == [("bob/a", 2, False)]
