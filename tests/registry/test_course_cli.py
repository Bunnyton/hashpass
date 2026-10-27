"""Tier1: `hashpass course …` -- courses from the console through the same API the web uses (2026-10-27)."""
import io

import pytest

from hashpass.course_cli import CourseApi, run_course
from hashpass.registry.remote import RemoteRegistry
from tests.registry.test_course_api import _course, _Courses
from tests.registry.test_course_api import pool as pool  # noqa: PLC0414  (the fixture)


def _run(pool: _Courses, *words: str, user: str = "bob") -> str:
    out = io.StringIO()
    api = CourseApi(RemoteRegistry(pool.url), pool.tok[user])
    assert run_course(api, user, list(words), out=out) == 0
    return out.getvalue()


def _layout(pool: _Courses, ref: str = "bob/linux") -> list[tuple[str, list[str]]]:
    view = pool.call("GET", f"/courses/{ref}", "bob")[1]
    return [(b["name"], [t["ref"] for t in b["tasks"]]) for b in view["blocks"]]


@pytest.mark.tier1
def test_a_block_and_its_tasks_are_separate_operations(pool: _Courses) -> None:
    _course(pool)
    _run(pool, "linux", "add", "block", "Основы")
    _run(pool, "Linux", "block", "Основы", "add", "git-init:1", "eve/regex:1")   # by title, own namespace
    assert _layout(pool) == [("Основы", ["bob/git-init:1", "eve/regex:1"])]
    shown = _run(pool, "bob/linux")
    assert "Основы" in shown and "bob/git-init:1" in shown


@pytest.mark.tier1
def test_adding_again_is_harmless_and_moves_a_task(pool: _Courses) -> None:
    _course(pool)
    _run(pool, "linux", "add", "block", "A")
    assert "уже есть" in _run(pool, "linux", "add", "block", "a")
    _run(pool, "linux", "block", "A", "add", "bob/git-init:1")
    _run(pool, "linux", "add", "block", "B")
    said = _run(pool, "linux", "block", "B", "add", "bob/git-init:1")
    assert "перенесено" in said
    assert _layout(pool) == [("A", []), ("B", ["bob/git-init:1"])]
    assert "уже в блоке" in _run(pool, "linux", "block", "B", "add", "bob/git-init:1")


@pytest.mark.tier1
def test_remove_rename_and_settings(pool: _Courses) -> None:
    _course(pool)
    _run(pool, "linux", "add", "block", "A")
    _run(pool, "linux", "block", "A", "add", "bob/git-init:1", "eve/regex:1")
    _run(pool, "linux", "block", "A", "rm", "eve/regex:1")
    _run(pool, "linux", "block", "A", "rename", "Git")
    assert _layout(pool) == [("Git", ["bob/git-init:1"])]
    _run(pool, "linux", "set", "title", "Linux и Git")
    assert pool.call("GET", "/courses/bob/linux", "bob")[1]["title"] == "Linux и Git"
    api = CourseApi(RemoteRegistry(pool.url), pool.tok["bob"])
    with pytest.raises(RuntimeError, match="не пуст"):          # the server's rule, said as is
        run_course(api, "bob", ["linux", "rm", "block", "Git"], out=io.StringIO())
    _run(pool, "linux", "block", "Git", "rm", "git-init:1")
    _run(pool, "linux", "rm", "block", "Git")
    assert _layout(pool) == []


@pytest.mark.tier1
def test_create_and_list(pool: _Courses) -> None:
    _run(pool, "new", "docker", "--title", "Docker")
    assert pool.call("GET", "/courses/bob/docker", "bob")[1]["title"] == "Docker"
    assert "bob/docker" in _run(pool)


@pytest.mark.tier1
def test_mistakes_are_said_plainly(pool: _Courses) -> None:
    _course(pool)
    api = CourseApi(RemoteRegistry(pool.url), pool.tok["bob"])
    with pytest.raises(RuntimeError, match="нет версии"):
        run_course(api, "bob", ["linux", "block", "A", "add", "git-init"], out=io.StringIO())
    with pytest.raises(RuntimeError, match="нет блока"):
        run_course(api, "bob", ["linux", "block", "Нет", "add", "git-init:1"], out=io.StringIO())
    with pytest.raises(RuntimeError, match="нет курса"):
        run_course(api, "bob", ["nope", "add", "block", "A"], out=io.StringIO())
    kid = CourseApi(RemoteRegistry(pool.url), pool.tok["kid"])
    with pytest.raises(RuntimeError, match=r"прав|нельзя|доступ"):
        run_course(kid, "kid", ["bob/linux", "add", "block", "A"], out=io.StringIO())
