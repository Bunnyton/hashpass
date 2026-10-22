"""Tier1: the hashengine work screen -- local and pool tabs (spec 2026-10-21 §10)."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from textual.widgets import Tree

from hashengine.tui import ConfirmDelete, EngineTUI
from hashpass.cli import Home
from hashpass.course_screen import AskScreen
from hashpass.imagestore.store import ImageStore

if TYPE_CHECKING:
    from pathlib import Path


class _Pool:
    def __init__(self) -> None:
        self.tagged: list[tuple[str, str]] = []
        self.forked: list[tuple[str, str]] = []
        self.settings: list[dict] = []

    def pool_images(self, *, token: str) -> list[dict]:  # noqa: ARG002
        return [{"ref": "bob/lab:1_v2", "repo": "bob/lab", "tag": "1", "n": 2, "latest": True, "kind": "task"},
                {"ref": "bob/lab:1_v1", "repo": "bob/lab", "tag": "1", "n": 1, "latest": False, "kind": "task"},
                {"ref": "eve/regex:1_v1", "repo": "eve/regex", "tag": "1", "n": 1, "latest": True, "kind": "task"}]

    def tag(self, src: str, to: str, *, token: str) -> str:  # noqa: ARG002
        self.tagged.append((src, to))
        return f"{src.partition(':')[0]}:{to}_v1"

    def fork(self, src: str, name: str, *, token: str) -> str:  # noqa: ARG002
        self.forked.append((src, name))
        return f"{name}:1_v1"

    def revisions(self, name: str, *, token: str) -> dict:  # noqa: ARG002
        return {"visibility": "public"}

    def repo_settings(self, name: str, *, token: str, **fields: object) -> dict:  # noqa: ARG002
        self.settings.append({"repo": name, **fields})
        return {}


def _app(tmp_path: Path, pool: _Pool) -> EngineTUI:
    env = Home(tmp_path / "h")
    store = ImageStore(env.images)
    src = tmp_path / "src"
    src.mkdir()
    store.save("bob/lab", "1", src, ())
    return EngineTUI(env, "http://pool", "bob", "tok", client=pool)


def _labels(app: EngineTUI, tree_id: str) -> list[str]:
    tree = app.query_one(tree_id, Tree)
    return [str(leaf.label) for node in tree.root.children for leaf in node.children]


async def _until(pilot, cond, tries: int = 40) -> None:
    for _ in range(tries):
        await pilot.pause(0.05)
        if cond():
            return
    msg = "condition never became true"
    raise AssertionError(msg)


async def _focus_leaf(app: EngineTUI, tree_id: str, ref: str) -> None:
    """Put the cursor on `ref`'s row, unfolding its repository first (others' start folded)."""
    tree = app.query_one(tree_id, Tree)
    tree.focus()
    for node in tree.root.children:
        for leaf in node.children:
            if isinstance(leaf.data, dict) and leaf.data["ref"] == ref:
                node.expand()
                tree.refresh()
                tree.move_cursor(leaf)


@pytest.mark.tier1
def test_both_tabs_list_their_images(tmp_path: Path) -> None:
    async def drive() -> None:
        app = _app(tmp_path, _Pool())
        async with app.run_test(size=(120, 32)) as pilot:
            await _until(pilot, lambda: len(_labels(app, "#pool-tree")) == 3)  # noqa: PLR2004
            assert any("bob/lab:1" in label and "своя сборка" in label for label in _labels(app, "#local-tree"))
            assert any("последняя" in label for label in _labels(app, "#pool-tree"))
            await pilot.press("tab")
            assert app.on_pool
            assert app.check_action("tag", ()) is True and app.check_action("push", ()) is False
    asyncio.run(drive())


async def _on_pool_row(app: EngineTUI, pilot, ref: str) -> None:
    await _until(pilot, lambda: len(_labels(app, "#pool-tree")) == 3)  # noqa: PLR2004
    await pilot.press("tab")
    await _focus_leaf(app, "#pool-tree", ref)
    await pilot.pause(0.1)
    await _focus_leaf(app, "#pool-tree", ref)                 # a folded repository unfolds first


@pytest.mark.tier1
def test_tag_on_the_pool_tab(tmp_path: Path) -> None:
    pool = _Pool()

    async def drive() -> None:
        app = _app(tmp_path, pool)
        async with app.run_test(size=(120, 32)) as pilot:
            await _on_pool_row(app, pilot, "bob/lab:1_v1")
            await pilot.press("t")
            await _until(pilot, lambda: isinstance(app.screen, AskScreen))
            await pilot.press(*"stable", "enter")
            await _until(pilot, lambda: pool.tagged == [("bob/lab:1_v1", "stable")])
    asyncio.run(drive())


@pytest.mark.tier1
def test_fork_someone_elses_revision(tmp_path: Path) -> None:
    pool = _Pool()

    async def drive() -> None:
        app = _app(tmp_path, pool)
        async with app.run_test(size=(120, 32)) as pilot:
            await _on_pool_row(app, pilot, "eve/regex:1_v1")
            await pilot.press("f")
            await _until(pilot, lambda: isinstance(app.screen, AskScreen))
            await pilot.press("enter")
            await _until(pilot, lambda: pool.forked == [("eve/regex:1_v1", "bob/regex")])
    asyncio.run(drive())


@pytest.mark.tier1
def test_switch_visibility_of_your_repository(tmp_path: Path) -> None:
    pool = _Pool()

    async def drive() -> None:
        app = _app(tmp_path, pool)
        async with app.run_test(size=(120, 32)) as pilot:
            await _on_pool_row(app, pilot, "bob/lab:1_v2")
            await pilot.press("s")
            await _until(pilot, lambda: pool.settings == [{"repo": "bob/lab", "visibility": "private"}])
    asyncio.run(drive())


@pytest.mark.tier1
def test_delete_a_local_copy(tmp_path: Path) -> None:
    async def drive() -> None:
        app = _app(tmp_path, _Pool())
        async with app.run_test(size=(120, 32)) as pilot:
            await pilot.pause(0.2)
            await _focus_leaf(app, "#local-tree", "bob/lab:1")
            await pilot.press("d")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmDelete))
            await pilot.press("y")
            await _until(pilot, lambda: not app.store.exists("bob/lab:1"))
    asyncio.run(drive())
