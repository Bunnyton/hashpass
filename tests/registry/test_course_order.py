"""
Tier1: open blocks one after another, and a block's tasks one after another -- one switch each.

User 2026-11-05: «возможность открывать последовательно блоки (одна кнопка в курсе) и
последовательно открывать задания — одна кнопка в блоке».
"""
from pathlib import Path

import pytest

from hashpass.registry import courses as c
from hashpass.registry.courses import CourseStore
from tests.registry.test_course_api import _Courses


@pytest.fixture
def course(tmp_path: Path) -> c.Course:
    course = CourseStore(tmp_path / "courses").create("bob", "linux")
    for name, repos in (("Git", ["bob/a", "bob/b", "bob/c"]), ("Regex", ["bob/r"]), ("Приз", ["bob/x"])):
        block = c.add_block(course, name)
        for repo in repos:
            c.add_task(course, repo, "1", 1, block, by="bob")
    return course


def _ids(course: c.Course) -> list[str]:
    return [b["id"] for b in course.blocks]


def _needs(course: c.Course, repo: str) -> list[str]:
    return next(t for _b, t in course.tasks() if t["repo"] == repo).get("needs", [])


@pytest.mark.tier1
def test_blocks_in_order_chain_each_to_the_one_before(course: c.Course) -> None:
    git, regex, prize = _ids(course)
    c.set_block_needs(course, prize, [git, "bob/a:1"])      # a block need goes, a task need stays
    c.set_blocks_in_order(course, on=True)
    assert course.blocks_in_order is True
    assert ["needs" in course.blocks[0], course.blocks[1]["needs"], course.blocks[2]["needs"]] == [
        False, [git], [regex, "bob/a:1"]]
    assert c.waiting_for(course, course.blocks[1], set()) == ["Git"]
    c.set_blocks_in_order(course, on=False)
    assert course.blocks_in_order is False
    assert ["needs" in course.blocks[1], course.blocks[2]["needs"]] == [False, ["bob/a:1"]]


@pytest.mark.tier1
def test_tasks_in_order_chain_inside_one_block(course: c.Course) -> None:
    git, _regex, _prize = _ids(course)
    c.set_task_needs(course, "bob/b", "1", ["bob/r:1"])     # a task of another block stays
    c.set_tasks_in_order(course, git, on=True)
    assert course.blocks[0]["tasks_in_order"] is True
    assert [_needs(course, r) for r in ("bob/a", "bob/b", "bob/c")] == [[], ["bob/a:1", "bob/r:1"], ["bob/b:1"]]
    assert _needs(course, "bob/x") == []                    # other blocks untouched
    c.set_tasks_in_order(course, git, on=False)
    assert "tasks_in_order" not in course.blocks[0]
    assert [_needs(course, r) for r in ("bob/a", "bob/b", "bob/c")] == [[], ["bob/r:1"], []]


@pytest.mark.tier1
def test_the_order_follows_moves_new_tasks_hidden_and_closed(course: c.Course) -> None:
    git, regex, prize = _ids(course)
    c.set_blocks_in_order(course, on=True)
    c.set_tasks_in_order(course, git, on=True)
    c.move_task(course, "bob/c", "1", -1)                   # a, c, b
    c.add_task(course, "bob/d", "1", 1, git, by="bob")      # a, c, b, d
    c.apply_order(course)
    assert [_needs(course, r) for r in ("bob/a", "bob/c", "bob/b", "bob/d")] == [
        [], ["bob/a:1"], ["bob/c:1"], ["bob/b:1"]]
    next(t for _b, t in course.tasks() if t["repo"] == "bob/b")["hidden"] = True
    c.apply_order(course)
    assert _needs(course, "bob/d") == ["bob/c:1"]           # a hidden task is stepped over
    c.set_block_open(course, regex, open_=False)            # students do not see Regex
    c.apply_order(course)
    assert course.blocks[2]["needs"] == [git]
    c.set_layout(course, [{"id": prize, "tasks": ["bob/x:1"]}, {"id": regex, "tasks": ["bob/r:1"]},
                          {"id": git, "tasks": ["bob/a:1", "bob/c:1", "bob/b:1", "bob/d:1"]}])
    c.apply_order(course)
    assert ["needs" in course.blocks[0], course.blocks[1]["needs"], course.blocks[2]["needs"]] == [
        False, [prize], [prize]]                             # Regex is closed: Git waits for Приз


@pytest.mark.tier1
def test_an_order_that_would_wait_forever_is_refused_and_nothing_changes(course: c.Course) -> None:
    c.set_task_needs(course, "bob/a", "1", ["bob/r:1"])     # Git's task waits for Regex's
    with pytest.raises(ValueError, match="ждут друг друга"):
        c.set_blocks_in_order(course, on=True)
    assert course.blocks_in_order is False and all("needs" not in b for b in course.blocks)


@pytest.mark.tier1
def test_the_store_keeps_the_order_on_every_edit(tmp_path: Path) -> None:
    store = CourseStore(tmp_path / "courses")
    store.create("bob", "linux")
    with store.edit("bob/linux") as course:
        git = c.add_block(course, "Git")
        c.add_task(course, "bob/a", "1", 1, git, by="bob")
        c.set_tasks_in_order(course, git, on=True)
    with store.edit("bob/linux") as course:
        c.add_task(course, "bob/b", "1", 1, git, by="bob")  # added later -- chained on save
    assert _needs(store.get("bob/linux"), "bob/b") == ["bob/a:1"]


# -- through the pool ------------------------------------------------------------

@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    for repo in ("bob/git-init", "bob/git-add", "bob/prize"):
        p.push(repo, "1", image=repo, task=repo)
    p.call("POST", "/courses", "bob", {"name": "linux"})
    for name, repos in (("Git", ["bob/git-init", "bob/git-add"]), ("Приз", ["bob/prize"])):
        block = p.call("POST", "/courses/bob/linux/blocks", "bob", {"name": name})[1]["id"]
        for repo in repos:
            p.call("POST", "/courses/bob/linux/tasks", "bob", {"repo": repo, "tag": "1", "block_id": block})
    return p


@pytest.mark.tier1
def test_one_call_puts_the_blocks_and_the_tasks_in_order(pool: _Courses) -> None:
    git, _prize = (b["id"] for b in pool.call("GET", "/courses/bob/linux", "bob")[1]["blocks"])
    assert pool.call("PUT", "/courses/bob/linux/order", "kid", {"blocks": True})[0] == 403  # noqa: PLR2004
    assert pool.call("PUT", "/courses/bob/linux/order", "bob", {"block": "nope", "tasks": True})[0] == 400  # noqa: PLR2004
    assert pool.call("PUT", "/courses/bob/linux/order", "bob", {})[0] == 400  # noqa: PLR2004
    assert pool.call("PUT", "/courses/bob/linux/order", "bob", {"blocks": True})[0] == 200  # noqa: PLR2004
    assert pool.call("PUT", "/courses/bob/linux/order", "bob", {"block": git, "tasks": True})[0] == 200  # noqa: PLR2004
    view = pool.call("GET", "/courses/bob/linux", "bob")[1]
    assert view["blocks_in_order"] is True
    assert [view["history"][0]["what"], view["history"][1]["what"]] == [
        "задания блока «Git» открываются по порядку", "блоки открываются по порядку"]
    assert (view["blocks"][0]["tasks_in_order"], view["blocks"][1]["needs"], view["blocks"][1]["after"]) == (
        True, [git], git)
    assert view["blocks"][0]["tasks"][1]["after"] == "bob/git-init:1"
    kid = pool.call("GET", "/courses/bob/linux", "kid")[1]
    assert kid["blocks"][0]["tasks"][1]["waiting_for"] == ["git-init"]
    assert pool.call("PUT", "/courses/bob/linux/order", "bob", {"blocks": False})[0] == 200  # noqa: PLR2004
    view = pool.call("GET", "/courses/bob/linux", "bob")[1]
    assert (view["blocks_in_order"], "needs" in view["blocks"][1]) == (False, False)
    assert view["history"][0]["what"] == "блоки открываются сразу"


@pytest.mark.tier1
def test_the_page_has_the_switches_for_staff_only(pool: _Courses) -> None:
    from tests.registry.test_course_web import _browser, _page  # noqa: PLC0415
    pool.call("PUT", "/courses/bob/linux/order", "bob", {"blocks": True})
    code, html = _page(_browser(pool, "bob"), f"{pool.url}/c/bob/linux")
    assert code == 200, html  # noqa: PLR2004
    assert "Блоки по порядку" in html and "aria-checked='true'" in html
    assert "data-api='PUT /courses/bob/linux/order'" in html and "Задания по порядку" in html
    assert "после «Git»" in html                             # the chained block says after what
    code, html = _page(_browser(pool, "kid"), f"{pool.url}/c/bob/linux")
    assert code == 200 and "Блоки по порядку" not in html and "Задания по порядку" not in html  # noqa: PLR2004
