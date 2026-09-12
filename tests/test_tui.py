"""Smoke tests for the student TUI (boots, groups tasks by block, quits cleanly)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from hashpass.tui import PoolTUI, TaskRow

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class _StubEnv:
    """Minimal stand-in for `hashpass.cli.Home` (only fields the TUI touches)."""

    images: Path
    root: Path
    registry: Path


class _StubClient:
    """Offline stand-in for `RemoteRegistry`: fixed catalog + empty progress + noop pulls."""

    def __init__(self, entries: list[dict]) -> None:
        self._entries = entries

    def catalog(self, *, token: str) -> list[dict]:  # noqa: ARG002
        return list(self._entries)

    def progress(self, *, token: str) -> dict:  # noqa: ARG002
        return {}

    def pull_many(self, *_a: object, **_k: object) -> list[str]:
        return []

    def pull_task(self, *_a: object, **_k: object) -> None:
        return


@pytest.mark.tier1
def test_tui_boots_with_tree_of_blocks_and_tasks(tmp_path: Path) -> None:
    """The Tree renders one node per block + one leaf per task, then quits on q."""
    env = _StubEnv(images=tmp_path / "images", root=tmp_path / "root",
                   registry=tmp_path / "registry")
    for p in (env.images, env.root, env.registry):
        p.mkdir(parents=True, exist_ok=True)
    entries = [
        {"number": 1, "ref": "hello:1", "block_name": "Основы", "available": True, "digest": ""},
        {"number": 2, "ref": "grep:1",  "block_name": "Основы", "available": False, "digest": ""},
        {"number": 3, "ref": "ps:1",    "block_name": "Процессы", "available": True, "digest": ""},
    ]

    async def _drive() -> None:
        app = PoolTUI(env, "http://pool.example", "stud", "tok")
        app.client = _StubClient(entries)
        app._download_row = lambda _row: None  # noqa: SLF001
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()   # let on_mount run
            from textual.widgets import Tree                # noqa: PLC0415
            tree = app.query_one("#tasks", Tree)
            # two block nodes under root
            block_nodes = list(tree.root.children)
            block_labels = [str(n.label) for n in block_nodes]
            assert any("Основы" in lbl for lbl in block_labels)
            assert any("Процессы" in lbl for lbl in block_labels)
            # each block has its tasks as leaves
            leaves = [str(leaf.label) for b in block_nodes for leaf in b.children]
            assert any("hello:1" in lbl for lbl in leaves)
            assert any("ps:1" in lbl for lbl in leaves)
            # closed task hides its ref
            assert any("закрыто" in lbl for lbl in leaves)
            assert not any("grep:1" in lbl for lbl in leaves)
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_task_row_status_labels() -> None:
    """A TaskRow computes the right one-line status labels across states."""
    r = TaskRow(ref="a:1", number=1, block="B", available=True, digest="")
    assert r.status_label() == "не начато · ожидает"
    r.state = "готово"
    assert r.status_label() == "не начато"
    r.local = True
    assert r.status_label() == "решено"
    r.server = "passed"
    assert r.status_label() == "зачтено"
    r.hidden = True
    assert r.status_label() == "закрыто"
