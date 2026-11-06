"""Tier1: a block opens once the blocks it needs are solved (user 2026-11-01: «решил блок -- получил приз»)."""
from pathlib import Path

import pytest

from hashpass.registry import course_copies as cc
from hashpass.registry import courses as c
from hashpass.registry.courses import CourseStore
from hashpass.registry.revisions import RepoIndex
from tests.registry.test_course_api import _Courses


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


@pytest.mark.tier1
def test_no_needs_by_default_nothing_waits(course: c.Course) -> None:
    assert all(c.waiting_for(course, b, set()) == [] for b in course.blocks)


@pytest.mark.tier1
def test_a_block_waits_for_every_block_it_needs(course: c.Course) -> None:
    git, regex, prize = _ids(course)
    c.set_block_needs(course, prize, [regex, git, regex])
    assert course.blocks[2]["needs"] == [git, regex]                 # course order, once each
    block = course.blocks[2]
    assert c.waiting_for(course, block, set()) == ["Git", "Regex"]
    assert c.waiting_for(course, block, {"bob/a:1", "bob/c:1"}) == ["Git"]      # Git half done
    assert c.waiting_for(course, block, {"bob/a:1", "bob/b:1", "bob/c:1"}) == []
    c.set_block_needs(course, prize, [])
    assert "needs" not in course.blocks[2]


@pytest.mark.tier1
def test_hidden_tasks_do_not_count(course: c.Course) -> None:
    git, _regex, prize = _ids(course)
    c.set_block_needs(course, prize, [git])
    course.blocks[0]["tasks"][1]["hidden"] = True                    # a draft nobody can solve
    assert c.waiting_for(course, course.blocks[2], {"bob/a:1"}) == []


@pytest.mark.tier1
def test_bad_needs_are_refused(course: c.Course) -> None:
    git, regex, prize = _ids(course)
    with pytest.raises(ValueError, match="такого блока нет"):
        c.set_block_needs(course, prize, ["nope"])
    with pytest.raises(ValueError, match="сам"):
        c.set_block_needs(course, prize, [prize])
    c.set_block_needs(course, regex, [git])
    c.set_block_needs(course, prize, [regex])
    with pytest.raises(ValueError, match="ждут друг друга"):
        c.set_block_needs(course, git, [prize])                     # git -> prize -> regex -> git


@pytest.mark.tier1
def test_a_removed_block_is_needed_no_more(course: c.Course) -> None:
    git, regex, prize = _ids(course)
    c.set_block_needs(course, prize, [git, regex])
    course.blocks[1]["tasks"] = []
    c.remove_block(course, regex)
    assert course.blocks[1]["needs"] == [git]


@pytest.mark.tier1
def test_copies_take_the_needs() -> None:
    parent = c.Course(id="p", owner="bob", name="linux")
    parent.blocks = [{"id": "b1", "name": "Git", "open": True, "tasks": []},
                     {"id": "b2", "name": "Приз", "open": True, "tasks": [], "needs": ["b1"]}]
    struct = cc.structure(parent)
    assert struct["blocks"][1]["needs"] == ["b1"] and "needs" not in struct["blocks"][0]
    copy = c.Course(id="m", owner="eve", name="linux")
    cc.apply_structure(copy, struct)
    assert copy.blocks[1]["needs"] == ["b1"]
    plain = {"auto_update": True, "blocks": [{"id": "b1", "name": "Git", "tasks": []}]}
    empty = {"auto_update": True, "blocks": [{"id": "b1", "name": "Git", "tasks": [], "needs": []}]}
    assert cc.diff(plain, empty) == []                              # an empty list is no list
    base = cc.structure(parent)
    theirs = cc.structure(parent)
    theirs["blocks"][1]["needs"] = []
    change = {"op": "block_needs", "id": "b2", "name": "Приз", "old": ["b1"], "new": []}
    assert cc.diff(base, theirs) == [change]
    assert cc.describe(change) == "блок «Приз» открыт без условий"
    merged, conflicts = cc.merge3(base, base, theirs)
    assert (conflicts, "needs" in merged["blocks"][1]) == ([], False)


# -- through the pool ------------------------------------------------------------

@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/git-init", "1", image="one", task="t1")
    p.push("bob/prize", "1", image="two", task="t2")
    p.call("POST", "/courses", "bob", {"name": "linux"})
    for name, repo in (("Git", "bob/git-init"), ("Приз", "bob/prize")):
        block = p.call("POST", "/courses/bob/linux/blocks", "bob", {"name": name})[1]["id"]
        p.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": repo, "tag": "1", "block_id": block})
    return p


def _rows(pool: _Courses, user: str) -> dict[str, dict]:
    return {r["ref"]: r for r in pool.call("GET", "/catalog?course=bob/linux", user)[1]["catalog"]}


@pytest.mark.tier1
def test_the_prize_opens_after_the_block(pool: _Courses) -> None:
    git, prize = (b["id"] for b in pool.call("GET", "/courses/bob/linux", "bob")[1]["blocks"])
    assert pool.call("PUT", f"/courses/bob/linux/blocks/{prize}", "kid", {"needs": [git]})[0] == 403  # noqa: PLR2004
    assert pool.call("PUT", f"/courses/bob/linux/blocks/{prize}", "bob", {"needs": ["nope"]})[0] == 400  # noqa: PLR2004
    assert pool.call("PUT", f"/courses/bob/linux/blocks/{prize}", "bob", {"needs": [git]})[0] == 200  # noqa: PLR2004
    view = pool.call("GET", "/courses/bob/linux", "bob")[1]
    assert view["history"][0]["what"] == "блок «Приз» откроется после: «Git»"
    assert view["blocks"][1]["needs"] == [git]
    row = _rows(pool, "kid")["bob/prize:1"]                          # seen, locked, with why
    assert (row["available"], row.get("preview"), row["waiting_for"]) == (False, None, ["Git"])
    kid_view = pool.call("GET", "/courses/bob/linux", "kid")[1]["blocks"][1]
    assert (kid_view["waiting_for"], kid_view["tasks"][0]["ref"]) == (["Git"], "bob/prize:1")
    staff = _rows(pool, "bob")["bob/prize:1"]                         # the staff run it as ever
    assert (staff["available"], staff["preview"], staff["waiting_for"]) == (False, True, ["Git"])
    digest = RepoIndex(pool.r.store.root / ".repos", "bob/git-init").get("1", 1).task_digest
    pool.call("POST", "/submit", "kid", {"task_ref": "bob/git-init:1", "course": "bob/linux",
                                         "digest": digest, "passed": True})
    row = _rows(pool, "kid")["bob/prize:1"]
    assert (row["available"], "waiting_for" in row) == (True, False)


@pytest.mark.tier1
def test_the_page_says_the_condition(pool: _Courses) -> None:
    from tests.registry.test_course_web import _browser, _page  # noqa: PLC0415
    git, prize = (b["id"] for b in pool.call("GET", "/courses/bob/linux", "bob")[1]["blocks"])
    pool.call("PUT", f"/courses/bob/linux/blocks/{prize}", "bob", {"needs": [git]})
    code, html = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")
    assert code == 200 and "🔒 откроется после: «Git»" in html  # noqa: PLR2004
    assert f'data-needs=\'["{git}"]\'' in html                        # the opener carries what is set
    assert "id='needs-dlg'" in html and "Когда откроется…" in html     # one dialog, not a form per menu
    code, html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")
    assert "🔒 откроется, когда решите: «Git»" in html and "needs-dlg" not in html
