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


def test_task_row_shows_the_version_and_which_one_was_solved() -> None:
    """User 2026-10-23: versions in the TUI; a credit for an older version stays, with a note."""
    r = TaskRow(ref="a:1", number=1, block="B", available=True, digest="", n=3)
    assert "версия 3" in r.tree_label() and "решалась" not in r.tree_label()
    r.server, r.solved_n = "passed", 3
    assert "решалась" not in r.status_label()
    r.solved_n = 2
    assert "зачтено (решалась версия 2)" in r.status_label()
    assert "решалась версия 2" in r.tree_label()
    assert "версия" not in TaskRow(ref="a:1", number=1, block="B", available=True, digest="").tree_label()


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
            assert "Загрузка lab:1" in panel and "bunnyton/debian:trixie" in panel, panel
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


class _EditClient(_StubClient):
    """A pool that remembers hide/move edits (role from `me`), like the real API."""

    def __init__(self, entries: list[dict], role: str) -> None:
        super().__init__(entries)
        self.role = role
        self.calls: list[tuple] = []

    def me(self, *, token: str) -> dict:  # noqa: ARG002
        return {"user": "t", "role": self.role}

    def set_task_hidden(self, ref: str, *, hidden: bool, token: str) -> dict:  # noqa: ARG002
        self.calls.append(("hidden", ref, hidden))
        for e in self._entries:
            if e["ref"] == ref:
                e["hidden"] = hidden
                e["preview"] = hidden
        return {}

    def move_task(self, ref: str, step: int, *, token: str) -> bool:  # noqa: ARG002
        if self.role != "admin":
            msg = "порядок заданий меняет только администратор"
            raise RuntimeError(msg)
        self.calls.append(("move", ref, step))
        i = next(k for k, e in enumerate(self._entries) if e["ref"] == ref)
        j = i + step
        self._entries[i], self._entries[j] = self._entries[j], self._entries[i]
        return True


def _edit_entries() -> list[dict]:
    return [{"number": 1, "ref": "a:1", "block_name": "Б", "available": True, "digest": ""},
            {"number": 2, "ref": "b:1", "block_name": "Б", "available": True, "digest": ""}]


def _cursor_to(app: PoolTUI, ref: str) -> None:
    from textual.widgets import Tree  # noqa: PLC0415
    tree = app.query_one("#tasks", Tree)
    tree.move_cursor(app._leaf_nodes[ref])  # noqa: SLF001


@pytest.mark.tier1
def test_staff_hides_and_shows_a_task_with_x(tmp_path: Path) -> None:
    # User (2026-10-12): «хочу править прямо внутри hashpass скрытость … и даже перемещать».
    client = _EditClient(_edit_entries(), role="author")

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", "t", "tok")
        app.client = client
        app._autoload = False  # noqa: SLF001
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            _cursor_to(app, "b:1")
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            assert client.calls == [("hidden", "b:1", True)]
            assert any("b:1" in s and "скрыто" in s for s in _leaves(app))
            _cursor_to(app, "b:1")
            await pilot.pause()
            await pilot.press("ч")                         # Russian layout, same key
            await pilot.pause()
            assert client.calls[-1] == ("hidden", "b:1", False)
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_admin_moves_a_task_with_shift_arrows_and_the_cursor_follows(tmp_path: Path) -> None:
    client = _EditClient(_edit_entries(), role="admin")

    async def _drive() -> None:
        from textual.widgets import Tree  # noqa: PLC0415
        app = PoolTUI(_env(tmp_path), "http://pool.example", "t", "tok")
        app.client = client
        app._autoload = False  # noqa: SLF001
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            _cursor_to(app, "b:1")
            await pilot.pause()
            await pilot.press("shift+up")
            await pilot.pause()
            assert client.calls == [("move", "b:1", -1)]
            assert [r.ref for r in app.rows] == ["b:1", "a:1"]
            node = app.query_one("#tasks", Tree).cursor_node
            assert node is not None and node.data.ref == "b:1"
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_an_author_cannot_move_and_a_student_cannot_edit(tmp_path: Path) -> None:
    for role in ("author", "student"):
        client = _EditClient(_edit_entries(), role=role)

        async def _drive(client: _EditClient = client) -> None:
            app = PoolTUI(_env(tmp_path), "http://pool.example", "t", "tok")
            app.client = client
            app._autoload = False  # noqa: SLF001
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                _cursor_to(app, "b:1")
                await pilot.pause()
                await pilot.press("shift+up")
                await pilot.press("K")
                await pilot.press("x")
                await pilot.pause()
                if client.role == "student":
                    assert client.calls == []
                else:
                    assert client.calls == [("hidden", "b:1", True)]   # hide yes, move no
                assert [r.ref for r in app.rows] == ["a:1", "b:1"]
                await pilot.press("q")

        asyncio.run(_drive())


@pytest.mark.tier1
def test_a_failed_download_says_why() -> None:
    from hashpass.tui import failure_note  # noqa: PLC0415
    note = failure_note("bunnyton/find-2:1",
                        RuntimeError("sudo tar failed to extract x (exit 1): sudo: a password is required"))
    assert "find-2" in note and "sudo" in note and "перезапусти" in note
    assert "сеть" in failure_note("x:1", RuntimeError("не удалось подключиться к пулу …"))
    row = TaskRow(ref="x:1", number=1, block="", available=True, digest="", state="ошибка",
                  error="нужен пароль sudo")
    assert "ошибка загрузки — нужен пароль sudo" in row.tree_label()


@pytest.mark.tier1
def test_staff_open_and_close_a_block_with_o(tmp_path: Path) -> None:
    # «блоки открывать для студентов тоже через hashpass»: o (щ) on a block or any of its tasks.
    entries = [{"number": 1, "ref": "a:1", "block_name": "Б", "block_id": "b1", "block_open": True,
                "available": True, "digest": ""}]

    class _BlockClient(_EditClient):
        def set_block_open(self, block_id: str, *, open_: bool, token: str) -> dict:  # noqa: ARG002
            self.calls.append(("block", block_id, open_))
            for e in self._entries:
                if e["block_id"] == block_id:
                    e["block_open"] = open_
                    e["available"] = open_
                    e["preview"] = not open_
            return {}

    client = _BlockClient(entries, role="author")

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", "t", "tok")
        app.client = client
        app._autoload = False  # noqa: SLF001
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            _cursor_to(app, "a:1")
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            assert client.calls == [("block", "b1", False)]
            from textual.widgets import Tree  # noqa: PLC0415
            heads = [str(b.label) for b in app.query_one("#tasks", Tree).root.children]
            assert any("закрыт" in h for h in heads), heads
            _cursor_to(app, "a:1")
            await pilot.pause()
            await pilot.press("щ")
            await pilot.pause()
            assert client.calls[-1] == ("block", "b1", True)
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_the_chosen_theme_survives_a_restart(tmp_path: Path) -> None:
    # User (2026-10-13): «сохрани выбор темы». Ctrl+P → Theme changes it; the next launch keeps it.
    env = _env(tmp_path)

    async def _choose() -> None:
        app = PoolTUI(env, "http://pool.example", "t", "tok")
        app.client = _StubClient([])
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.theme = "nord"
            await pilot.pause()
            await pilot.press("q")

    async def _reopen() -> str:
        app = PoolTUI(env, "http://pool.example", "t", "tok")
        app.client = _StubClient([])
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            theme = app.theme
            await pilot.press("q")
        return theme

    asyncio.run(_choose())
    assert asyncio.run(_reopen()) == "nord"


@pytest.mark.tier1
def test_downloads_wait_while_a_task_console_is_open(tmp_path: Path) -> None:
    """User, 2026-10-15: «подлагивать чтение стало, рывками» -- background pulls ran during the task."""
    app = PoolTUI(_env(tmp_path), "http://pool.example", "stud", "tok")
    row = TaskRow(ref="a:1", number=1, block="Б", available=True, digest="")
    taken: list[str] = []
    worker = threading.Thread(target=lambda: taken.append(app._next_job().ref), daemon=True)  # noqa: SLF001
    with app.downloads_paused():
        app._enqueue(row)  # noqa: SLF001
        worker.start()
        worker.join(timeout=0.5)
        assert taken == []                        # a console is open: the queue waits
    worker.join(timeout=2)
    assert taken == ["a:1"]                       # back in the catalog: it goes on


@pytest.mark.tier1
def test_vim_keys_walk_the_catalog(tmp_path: Path) -> None:
    # User, 2026-10-15: «в hashpass интерфейс заданий добавь поддержку клавиш как в vim hjkl».
    client = _EditClient(_edit_entries(), role="student")

    async def _drive() -> None:
        from textual.widgets import Tree  # noqa: PLC0415
        app = PoolTUI(_env(tmp_path), "http://pool.example", "t", "tok")
        app.client = client
        app._autoload = False  # noqa: SLF001
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tasks", Tree)

            def at() -> object:
                node = tree.cursor_node
                return node.data.ref if isinstance(node.data, TaskRow) else "block"

            _cursor_to(app, "a:1")
            await pilot.pause()
            await pilot.press("j")
            assert at() == "b:1"
            await pilot.press("k")
            assert at() == "a:1"
            await pilot.press("о")                          # j on the Russian layout
            assert at() == "b:1"
            await pilot.press("h")                          # task -> its block
            assert at() == "block"
            await pilot.press("h")                          # block -> folded
            await pilot.pause()
            assert not tree.cursor_node.is_expanded
            await pilot.press("l")                          # block -> unfolded, first task
            await pilot.pause()
            assert tree.cursor_node.is_expanded or at() == "a:1"
            await pilot.press("l")
            assert at() == "a:1"
            await pilot.press("G")
            assert at() == "b:1"
            await pilot.press("g")
            assert at() == "block"
            assert client.calls == []                       # walking edits nothing
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_admin_moves_a_task_with_shift_j_k(tmp_path: Path) -> None:
    client = _EditClient(_edit_entries(), role="admin")

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", "t", "tok")
        app.client = client
        app._autoload = False  # noqa: SLF001
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            _cursor_to(app, "b:1")
            await pilot.pause()
            await pilot.press("K")
            await pilot.pause()
            assert client.calls == [("move", "b:1", -1)]
            await pilot.press("J")
            await pilot.pause()
            assert client.calls[-1] == ("move", "b:1", 1)
            await pilot.press("q")

    asyncio.run(_drive())


def test_the_plain_task_list_says_which_version_was_solved() -> None:
    from hashpass.cli import _status_badge  # noqa: PLC0415
    assert "решалась версия 1" in _status_badge({"server": "passed", "n": 2, "solved_n": 1})
    assert "решалась" not in _status_badge({"server": "passed", "n": 2, "solved_n": 2})


def test_a_pass_outside_the_course_is_marked_in_it() -> None:
    """User 2026-10-23: passed outside the course -- passed in it too, «пройдено не в курсе»."""
    from hashpass.cli import _status_badge  # noqa: PLC0415
    r = TaskRow(ref="a:1", number=1, block="B", available=True, digest="", n=3, solved_n=3, outside=True)
    r.server = "passed"
    assert "зачтено (пройдено не в курсе)" in r.status_label()
    assert "пройдено не в курсе" in _status_badge({"server": "passed", "n": 3, "solved_n": 3, "outside": True})


def test_a_new_version_waits_for_a_yes() -> None:
    """A task with an older copy here says so and is not queued by itself (TODO: спрашивать «скачать?»)."""
    from hashpass.tui import updates_to_ask  # noqa: PLC0415
    old = TaskRow(ref="a:1", number=1, block="B", available=True, digest="d2", n=2, state="обновление")
    new = TaskRow(ref="b:1", number=2, block="B", available=True, digest="d1", n=1, state="ожидает")
    assert "есть версия 2" in old.download_word()
    assert updates_to_ask([old, new], asked=set()) == [old]
    assert updates_to_ask([old, new], asked={("a:1", "d2")}) == []
