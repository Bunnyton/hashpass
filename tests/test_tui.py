"""Smoke tests for the student TUI (boots, groups tasks by block, quits cleanly)."""
from __future__ import annotations

import asyncio
import threading
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
            from textual.widgets import Tree  # noqa: PLC0415
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
    """A TaskRow computes the right two-badge status across states (local × server)."""
    r = TaskRow(ref="a:1", number=1, block="B", available=True, digest="")
    assert r.status_label() == "не решено · не зачтено · не загружено"
    r.state = "в очереди"
    assert r.status_label() == "не решено · не зачтено · в очереди"
    r.state, r.progress = "грузится", 0.42
    assert r.status_label() == "не решено · не зачтено · грузится 42%"
    r.state = "готово"
    assert r.status_label() == "не решено · не зачтено · загружено"
    r.local = True
    assert r.status_label() == "решено · не зачтено · загружено"   # locally done, not credited
    r.server = "passed"
    assert r.status_label() == "решено · зачтено · загружено"      # both -- fully done
    r.local = False
    assert r.status_label() == "не решено · зачтено · загружено"   # server credit only
    r.hidden = True
    assert r.status_label() == "закрыто"


def _env(tmp_path: Path) -> _StubEnv:
    env = _StubEnv(images=tmp_path / "images", root=tmp_path / "root",
                   registry=tmp_path / "registry")
    for p in (env.images, env.root, env.registry):
        p.mkdir(parents=True, exist_ok=True)
    return env


def _leaves(app: PoolTUI) -> list[str]:
    from textual.widgets import Tree  # noqa: PLC0415
    tree = app.query_one("#tasks", Tree)
    return [str(n.label) for b in tree.root.children for n in (b.children or [b])]


@pytest.mark.tier1
def test_tui_shows_hidden_tasks_to_staff_with_ref(tmp_path: Path) -> None:
    """An author/admin sees a hidden task's ref with a «скрыто» badge -- not «закрыто», not empty."""
    entries = [{"number": 1, "ref": "lab:1", "block_name": "Б", "available": False,
                "hidden": True, "preview": True, "digest": ""}]

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", "teacher", "tok")
        app.client = _StubClient(entries)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            leaves = _leaves(app)
            assert any("lab:1" in s and "скрыто" in s for s in leaves), leaves
            assert app.rows[0].hidden is False
            await pilot.press("q")

    asyncio.run(_drive())


class _DownClient(_StubClient):
    def catalog(self, *, token: str) -> list[dict]:  # noqa: ARG002
        msg = "не удалось подключиться к пулу https://x:8080: wrong version number"
        raise RuntimeError(msg)


@pytest.mark.tier1
def test_tui_reports_unreachable_pool_instead_of_empty(tmp_path: Path) -> None:
    """A failed /catalog must say the pool is unreachable, not «в пуле пока нет заданий»."""

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "https://x:8080", "teacher", "tok")
        app.client = _DownClient([])
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            leaves = " ".join(_leaves(app))
            assert "нет заданий" not in leaves
            assert "не удалось подключиться" in leaves
            await pilot.press("q")

    asyncio.run(_drive())


class _SlowClient(_StubClient):
    """Downloads two layers in parallel, reporting progress; blocks until `go` is set."""

    def __init__(self, entries: list[dict], go: threading.Event) -> None:
        super().__init__(entries)
        self.go = go

    def image_digest(self, _ref: str) -> str | None:
        return "sha"                                   # the pool has a base -> it joins the batch

    def pull_many(self, refs: list[str], _store: object, **kw: object) -> list[str]:
        progress = kw["progress"]
        layers = [*refs]
        for ref in layers:
            progress(ref, 0, None)
        for ref in layers:
            progress(ref, 512, 1024)
        self.go.wait(5)
        for ref in layers:
            progress(ref, 1024, 1024)
        return layers


@pytest.mark.tier1
def test_tui_starts_downloading_on_launch_with_layer_bars(tmp_path: Path, monkeypatch) -> None:
    """On launch every open task queues itself (docker-pull); the panel shows per-layer bars."""
    from hashpass import cli  # noqa: PLC0415
    monkeypatch.setattr(cli, "base_ref", lambda: "bunnyton/debian:trixie")
    env = _env(tmp_path)
    entries = [{"number": 1, "ref": "lab:1", "block_name": "Б", "available": True, "digest": ""},
               {"number": 2, "ref": "lab:2", "block_name": "Б", "available": True, "digest": ""},
               {"number": 3, "ref": "shut:1", "block_name": "Б", "available": False, "digest": ""}]
    go = threading.Event()

    async def _drive() -> None:
        app = PoolTUI(env, "http://pool.example", "stud", "tok")
        app.client = _SlowClient(entries, go)
        async with app.run_test(size=(120, 30)) as pilot:
            app.store.exists = lambda _ref: False      # the stub pull stores nothing -> «ошибка»
            await pilot.pause(0.6)                      # no key pressed: downloads start by themselves
            panel = str(app.query_one("#downloads").content)
            assert "Загрузка №1 lab:1" in panel and "bunnyton/debian:trixie" in panel, panel
            assert "50%" in panel and "в очереди ещё: 1" in panel, panel
            states = [r.state for r in app.rows]
            assert states == ["грузится", "в очереди", "ожидает"], states   # closed task is skipped
            go.set()
            for _ in range(40):
                await pilot.pause(0.1)
                if all(r.state == "ошибка" for r in app.rows[:2]):
                    break
            await pilot.pause(0.4)
            assert [r.state for r in app.rows[:2]] == ["ошибка", "ошибка"]
            assert str(app.query_one("#downloads").content) == ""   # panel hides when idle
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_enter_on_a_queued_task_moves_it_first(tmp_path: Path) -> None:
    """Enter on a task waiting in the queue makes it the next one to download."""

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", "stud", "tok")
        app._autoload = False  # noqa: SLF001
        app.client = _StubClient([])
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            rows = [TaskRow(ref=f"t:{i}", number=i, block="Б", available=True, digest="")
                    for i in (1, 2, 3)]
            with app._wake:  # noqa: SLF001  (hold the worker so the queue stays put)
                app._stopping = True  # noqa: SLF001
            for r in rows:
                app._enqueue(r)  # noqa: SLF001
            app._enqueue(rows[2], first=True)  # noqa: SLF001
            assert [r.ref for r in app._pending] == ["t:3", "t:1", "t:2"]  # noqa: SLF001
            await pilot.press("q")

    asyncio.run(_drive())
