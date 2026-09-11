"""Smoke tests for the student TUI (boots, renders rows, quits cleanly)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from hashpass.tui import PoolTUI, TaskRow

if TYPE_CHECKING:
    from pathlib import Path

_MIN_ITEMS = 3   # one block header + two task rows


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
def test_tui_boots_and_lists_rows(tmp_path: Path) -> None:
    """The TUI mounts, renders one header + one row per catalog entry, and quits on q."""
    env = _StubEnv(images=tmp_path / "images", root=tmp_path / "root",
                   registry=tmp_path / "registry")
    for p in (env.images, env.root, env.registry):
        p.mkdir(parents=True, exist_ok=True)
    entries = [
        {"number": 1, "ref": "hello:1", "block_name": "Основы", "available": True, "digest": ""},
        {"number": 2, "ref": "grep:1",  "block_name": "Основы", "available": False, "digest": ""},
    ]

    async def _drive() -> None:
        app = PoolTUI(env, "http://pool.example", "stud", "tok")
        # replace the network client + block download so the app runs offline
        app.client = _StubClient(entries)
        app._download_row = lambda _row: None  # noqa: SLF001
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()   # let on_mount run
            lv = app.query_one("#tasks")
            # one block header + two task rows = at least 3 items
            assert len(lv.children) >= _MIN_ITEMS
            # each list item wraps one Static; read its rendered content
            rendered = "\n".join(
                str(w.content) for it in lv.children
                for w in it.query("Static"))
            assert "hello:1" in rendered
            # the closed task is shown as "закрыто", not by its ref
            assert "закрыто" in rendered
            assert "grep:1" not in rendered
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_task_row_status_labels() -> None:
    """A TaskRow computes the right one-line status labels across download/verdict states."""
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
