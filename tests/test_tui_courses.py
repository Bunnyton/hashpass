"""Tier1: picking a course in the hashpass TUI (spec 2026-10-21 §9)."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from hashpass import my_courses
from hashpass.cli import Home
from hashpass.course_screen import AskScreen, CoursePicker
from hashpass.registry.remote import use_course
from hashpass.tui import PoolTUI

if TYPE_CHECKING:
    from pathlib import Path

URL = "http://pool"


class _Client:
    def __init__(self, *, courses: bool = True) -> None:
        self.has_courses = courses
        self.joined: list[str] = []
        self.requests: list[tuple[str, str]] = []

    def me(self, *, token: str) -> dict:  # noqa: ARG002
        return {"role": "student"}

    def courses(self, q: str = "", *, token: str) -> list[dict] | None:  # noqa: ARG002
        if not self.has_courses:
            return None
        rows = [{"ref": "bob/closed", "title": "Закрытый", "visibility": "private", "role": None},
                {"ref": "bob/open", "title": "Открытый", "visibility": "public", "role": None}]
        return [r for r in rows if q.casefold() in f"{r['ref']} {r['title']}".casefold()]

    def course_view(self, ref: str, *, token: str) -> dict:  # noqa: ARG002
        if ref == "bob/open":
            return {"ref": ref, "title": "Открытый", "visibility": "public", "role": None, "blocks": []}
        return {"ref": ref, "title": "Закрытый", "visibility": "private", "access": "request"}

    def join(self, ref: str, invite: str = "", *, token: str) -> dict:  # noqa: ARG002
        self.joined.append(ref)
        return {"joined": ref}

    def request_access(self, ref: str, comment: str = "", *, token: str) -> None:  # noqa: ARG002
        self.requests.append((ref, comment))

    def catalog(self, *, token: str) -> list[dict]:  # noqa: ARG002
        return []

    def progress(self, *, token: str) -> dict:  # noqa: ARG002
        return {}


async def _until(pilot, cond, tries: int = 40) -> None:
    for _ in range(tries):
        await pilot.pause(0.05)
        if cond():
            return
    msg = "condition never became true"
    raise AssertionError(msg)


@pytest.fixture(autouse=True)
def _forget_course() -> None:
    yield
    use_course(URL, None)


@pytest.mark.tier1
def test_first_start_asks_for_a_course_and_joins_a_public_one(tmp_path: Path) -> None:
    client = _Client()

    async def drive() -> None:
        app = PoolTUI(Home(tmp_path / "h"), URL, "kid", "tok")
        app.client = client
        async with app.run_test(size=(110, 32)) as pilot:
            await _until(pilot, lambda: isinstance(app.screen, CoursePicker))
            await pilot.press(*"open")
            await _until(pilot, lambda: [r["ref"] for r in app.screen.rows] == ["bob/open"])
            await pilot.press("enter")
            await _until(pilot, lambda: not isinstance(app.screen, CoursePicker))
            assert my_courses.current(app.env.root, URL) == "bob/open"
            assert client.joined == ["bob/open"]
            assert "bob/open" in app.title
    asyncio.run(drive())


@pytest.mark.tier1
def test_a_closed_course_becomes_an_access_request(tmp_path: Path) -> None:
    client = _Client()

    async def drive() -> None:
        app = PoolTUI(Home(tmp_path / "h"), URL, "kid", "tok")
        app.client = client
        async with app.run_test(size=(110, 32)) as pilot:
            await _until(pilot, lambda: isinstance(app.screen, CoursePicker))
            await pilot.press(*"закр")
            await _until(pilot, lambda: [r["ref"] for r in app.screen.rows] == ["bob/closed"])
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, AskScreen))
            await pilot.press(*"ИТ-21", "enter")
            await _until(pilot, lambda: client.requests == [("bob/closed", "ИТ-21")])
            assert my_courses.current(app.env.root, URL) is None
    asyncio.run(drive())


@pytest.mark.tier1
def test_a_pool_without_courses_works_as_before(tmp_path: Path) -> None:
    async def drive() -> None:
        app = PoolTUI(Home(tmp_path / "h"), URL, "kid", "tok")
        app.client = _Client(courses=False)
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause(0.3)
            assert not isinstance(app.screen, CoursePicker)
            assert app.check_action("courses", ()) is False
    asyncio.run(drive())
