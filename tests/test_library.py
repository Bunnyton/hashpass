"""Tier1: the client's search over every task and image -- here and on the pool (TODO 2026-10-23)."""
import pytest

from hashpass.library import collect


def _pool(name: str, *, task: bool, n: int = 1, about: str = "") -> dict:
    return {"name": name, "task": task, "about": about, "updated": "2026-10-23T10:00:00Z",
            "tags": [{"tag": "1", "n": n, "ref": f"{name}:1_v{n}", "task": task}]}


@pytest.mark.tier1
def test_local_builds_come_first_tasks_apart_from_images_then_the_pool() -> None:
    local = [("bob/lab:1", "task"), ("bob/base:1", "image"), ("bunnyton/links:1_v4", "task")]
    pool = [_pool("bunnyton/links", task=True, n=4, about="Ссылки"), _pool("alice/web", task=False)]
    rows = collect(local, pool, "")
    assert [(r.section, r.ref) for r in rows] == [
        ("Задания на этой машине", "bob/lab:1"),
        ("Задания на этой машине", "bunnyton/links:1_v4"),
        ("Образы на этой машине", "bob/base:1"),
        ("Задания на пуле", "bunnyton/links:1"),
        ("Образы на пуле", "alice/web:1"),
    ]
    links = rows[3]
    assert (links.kind, links.n, links.about, links.local) == ("task", 4, "Ссылки", True)  # downloaded already


@pytest.mark.tier1
def test_the_query_filters_by_name_and_description() -> None:
    pool = [_pool("bunnyton/links", task=True, about="Символьные ссылки"), _pool("alice/web", task=False)]
    assert [r.ref for r in collect([("bob/lab:1", "task")], pool, "СИМВОЛ")] == ["bunnyton/links:1"]
    assert [r.ref for r in collect([("bob/lab:1", "task")], pool, "lab")] == ["bob/lab:1"]


class _Pool:
    def repos(self, _q: str, token: str | None = None) -> list[dict]:  # noqa: ARG002
        return [_pool("alice/web", task=False)]


def _pick(monkeypatch: pytest.MonkeyPatch, tmp_path, key: str, ref: str) -> object:
    """Open the list, put the cursor on `ref`, press `key`; return what the screen gave back."""
    import asyncio  # noqa: PLC0415

    from textual.app import App  # noqa: PLC0415
    from textual.widgets import Tree  # noqa: PLC0415

    from hashpass import library  # noqa: PLC0415
    from hashpass.cli import Home  # noqa: PLC0415
    monkeypatch.setattr(library.LibraryScreen, "_local", lambda _self: [("bob/lab:1", "task")])
    got: list[object] = []

    class _Host(App):
        def on_mount(self) -> None:
            self.push_screen(library.LibraryScreen(Home(tmp_path), _Pool(), "tok"), got.append)

    async def drive() -> None:
        app = _Host()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.pause()
            tree = app.screen.query_one("#lib-tree", Tree)
            tree.focus()
            node = next(n for s in tree.root.children for n in s.children if n.data and n.data.ref == ref)
            tree.move_cursor(node)
            await pilot.press(key)
            await pilot.pause()
    asyncio.run(drive())
    return got[0] if got else None


@pytest.mark.tier1
def test_p_sends_a_build_of_this_machine_to_the_pool(monkeypatch, tmp_path) -> None:
    """User 2026-10-24: «оставь возможность из интерфейса локальные образы запушить»."""
    chosen = _pick(monkeypatch, tmp_path, "p", "bob/lab:1")
    assert chosen is not None and (chosen.ref, chosen.action) == ("bob/lab:1", "push")
    assert _pick(monkeypatch, tmp_path, "p", "alice/web:1") is None     # a pool row: nothing to send


@pytest.mark.tier1
def test_a_push_choice_runs_push_with_the_message_asked(monkeypatch, tmp_path) -> None:
    from hashpass import cli, library  # noqa: PLC0415
    from hashpass.cli import Home  # noqa: PLC0415
    calls: list[tuple] = []
    monkeypatch.setattr(cli, "cmd_push", lambda _env, ref, **k: calls.append((ref, k.get("message"))) or 0)
    monkeypatch.setattr(cli, "cmd_engine_run", lambda *_a, **_k: calls.append(("run",)) or 0)
    monkeypatch.setattr("hashpass.tui._read_line", lambda _prompt="": "новый шаг")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    library.run_entry(Home(tmp_path), library.Entry("Задания на этой машине", "bob/lab:1", "task",
                                                    local=True, action="push"))
    assert calls == [("bob/lab:1", "новый шаг")]
