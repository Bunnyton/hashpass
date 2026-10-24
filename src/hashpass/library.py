"""
Every task and image in one searchable list -- on this machine and on the pool (TODO 2026-10-23).

«На клиенте дай возможность искать по образам всем, и локальные образы (задания) и их выполнять
(проходить)»: own builds show up right after `hashpass build`, images apart from tasks, and Enter
runs any of them. A run outside a course gives no course credit; a pool version solved here is
kept in the profile (and shown in a course holding it as «пройдено не в курсе»).
"""
from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from rich.markup import escape
from textual import work
from textual.app import App
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Tree

from hashpass.imagestore.store import ImageStore
from hashpass.registry.revisions import parse_version

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from hashpass.cli import Home

_SECTIONS = ("Задания на этой машине", "Образы на этой машине", "Задания на пуле", "Образы на пуле")


@dataclass
class Entry:
    """One row of the list: what it is, where it lives, how to run it (`ref`)."""

    section: str
    ref: str
    kind: str                # "task" | "image"
    n: int = 0               # the pool's newest version (pool rows)
    about: str = ""
    local: bool = False      # a copy is on this machine
    action: str = "run"      # what the list asks for: "run", or "push" (a build of this machine)

    def label(self) -> str:
        """Return the row as the tree shows it (Rich markup)."""
        bits = [f"[b]{escape(self.ref)}[/]"]
        if self.n:
            bits.append(f"[dim]версия {self.n}[/]")
        if self.section.endswith("пуле") and self.local:
            bits.append("[green]загружено[/]")
        if self.about:
            bits.append(f"[dim]· {escape(self.about[:70])}[/]")
        return "  ".join(bits)


def _base(ref: str) -> str:
    """`x:1_v4` -> `x:1` (a pool version is still the tag it belongs to)."""
    name, _, version = ref.partition(":")
    return f"{name}:{parse_version(version)[0]}" if version else ref


def collect(local: list[tuple[str, str]], pool: list[dict] | None, query: str) -> list[Entry]:
    """
    Build the list: local tasks, local images, then the pool's tasks and images.

    `local` -- (ref, kind) from the image store; `pool` -- `RemoteRegistry.repos()` rows (None:
    offline). `query` matches the name or the description, case-insensitive.
    """
    q = query.casefold().strip()
    here = {_base(ref) for ref, _k in local}
    rows = [Entry(_SECTIONS[0] if kind == "task" else _SECTIONS[1], ref, "task" if kind == "task" else "image")
            for ref, kind in sorted(local, key=lambda r: r[0])]
    for repo in pool or []:
        for tag in repo.get("tags") or []:
            ref = f"{repo['name']}:{tag['tag']}"
            task = bool(tag.get("task", repo.get("task")))
            rows.append(Entry(_SECTIONS[2] if task else _SECTIONS[3], ref, "task" if task else "image",
                              n=int(tag.get("n") or 0), about=str(repo.get("about") or ""),
                              local=ref in here))
    rows = [r for r in rows if not q or q in r.ref.casefold() or q in r.about.casefold()]
    return sorted(rows, key=lambda r: _SECTIONS.index(r.section))     # stable: keeps the order inside


class LibraryScreen(Screen["Entry | None"]):
    """A search line over a tree of sections; Enter -- run the row, Esc -- back."""

    BINDINGS = [  # noqa: RUF012
        Binding("escape", "back", "Назад"),
        Binding("f5", "reload", "Обновить"),
        Binding("p,з", "push", "На пул"),
        Binding("slash,f,F,а,А", "search", "Поиск", show=False),   # not the app's «open the list» again
    ]
    DEFAULT_CSS = """
    LibraryScreen #lib-q { margin: 0 1; }
    LibraryScreen #lib-tree { padding: 0 1; }
    LibraryScreen #lib-head { padding: 0 1; color: $text-muted; }
    """

    def __init__(self, env: Home, client: object | None, token: str = "") -> None:
        """Bind to this machine's images and (when signed in) the pool."""
        super().__init__()
        self.env, self.client, self.token = env, client, token
        self.pool: list[dict] | None = None
        self.note = "пул: загружаю…" if client is not None else "пул не задан — только эта машина"

    def compose(self) -> ComposeResult:
        """Search line, a status line, the tree, the keys."""
        yield Input(placeholder="поиск по заданиям и образам: имя или описание", id="lib-q")
        yield Label(self.note, id="lib-head")
        yield Tree("все", id="lib-tree")
        yield Footer()

    def on_mount(self) -> None:
        """Paint what is here at once; the pool arrives in the background."""
        self.query_one("#lib-tree", Tree).show_root = False
        self._paint()
        self.query_one("#lib-q", Input).focus()
        self.action_reload()

    def action_reload(self) -> None:
        """F5: ask the pool again (a fresh push of someone else shows up)."""
        if self.client is not None:
            self._load_pool()

    @work(thread=True, exclusive=True)
    def _load_pool(self) -> None:
        try:
            rows = self.client.repos("", token=self.token or None)
            note = "пул: старая версия — поиск только по этой машине" if rows is None else ""
        except Exception as exc:                          # noqa: BLE001  (offline: the local list stays)
            rows, note = None, f"пул недоступен: {str(exc).splitlines()[0][:80] if str(exc) else type(exc).__name__}"
        self.app.call_from_thread(self._loaded, rows, note)

    def _loaded(self, rows: list[dict] | None, note: str) -> None:
        self.pool = rows
        self.query_one("#lib-head", Label).update(note or "Enter — запустить · p — свою сборку на пул · задание с пула "
                                                          "решается без зачёта в курс, но попадает в профиль")
        self._paint()

    def _local(self) -> list[tuple[str, str]]:
        from hashpass.cli import _kind  # noqa: PLC0415  (avoid an import cycle at module load)
        store = ImageStore(self.env.images)
        return [(ref, _kind(store, ref)) for ref in store.list()]

    def _paint(self) -> None:
        tree = self.query_one("#lib-tree", Tree)
        tree.clear()
        rows = collect(self._local(), self.pool, self.query_one("#lib-q", Input).value)
        nodes: dict[str, object] = {}
        for row in rows:
            if row.section not in nodes:
                nodes[row.section] = tree.root.add(f"[b]{row.section}[/]", expand=True)
            nodes[row.section].add_leaf(row.label(), data=row)
        if not rows:
            tree.root.add_leaf("[dim]ничего не нашлось[/]")

    def on_input_changed(self, _event: Input.Changed) -> None:
        """Filter as one types."""
        self._paint()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter in the search line: go to the list."""
        self.query_one("#lib-tree", Tree).focus()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter on a row: run it."""
        if isinstance(event.node.data, Entry):
            self.dismiss(event.node.data)

    def action_push(self) -> None:
        """P: send a build of this machine to the pool (user 2026-10-24: «из интерфейса запушить»)."""
        tree = self.query_one("#lib-tree", Tree)
        row = tree.cursor_node.data if tree.cursor_node is not None else None
        if not isinstance(row, Entry) or row.section not in _SECTIONS[:2]:
            self.notify("На пул отправляется сборка этой машины — выберите строку из «… на этой машине»",
                        severity="warning")
            return
        self.dismiss(replace(row, action="push"))

    def action_search(self) -> None:
        """/ or f: back to the search line."""
        self.query_one("#lib-q", Input).focus()

    def action_back(self) -> None:
        """Esc: back (from the list to the search line first)."""
        if self.query_one("#lib-tree", Tree).has_focus:
            self.query_one("#lib-q", Input).focus()
            return
        self.dismiss(None)


def run_entry(env: Home, entry: Entry) -> None:
    """Do the chosen row in the real terminal: solve a task, an image's shell, or push a build."""
    from hashpass import cli  # noqa: PLC0415
    from hashpass.tui import _read_line  # noqa: PLC0415
    io = cli.Io(read=_read_line, write=lambda s: sys.stdout.write(s), clock=cli._now_iso)  # noqa: PLW0108, SLF001
    sys.stdout.write("\x1b[2J\x1b[H")
    try:
        if entry.action == "push":
            message = io.read(f"{entry.ref} -> на пул. Что поменялось (Enter -- без комментария): ").strip()
            cli.cmd_push(env, entry.ref, io=io, message=message)
            with contextlib.suppress(EOFError, KeyboardInterrupt):
                input("Enter — назад к списку ")
        else:
            cli.cmd_engine_run(env, entry.ref, None, io)
    except Exception as exc:                              # noqa: BLE001  (say it, back to the list)
        what = "отправить" if entry.action == "push" else "запустить"
        sys.stdout.write(f"\x1b[31mне удалось {what} {entry.ref}: {exc}\x1b[0m\n")
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input("Enter — назад к списку ")


class LibraryApp(App):
    """`hashpass work`: the list on its own, for those who build and try their tasks."""

    def __init__(self, env: Home) -> None:
        """Bind to the configured pool (signed in or not)."""
        super().__init__()
        from hashpass.account import current  # noqa: PLC0415
        from hashpass.registry.remote import RemoteRegistry  # noqa: PLC0415
        self.env = env
        url, _user, self.token = current(env)
        self.client = RemoteRegistry(url, token=self.token) if url else None

    def on_mount(self) -> None:
        """Open the list."""
        self.title = "hashpass — задания и образы"
        self._open()

    def _open(self) -> None:
        self.push_screen(LibraryScreen(self.env, self.client, self.token), self._chosen)

    def _chosen(self, entry: Entry | None) -> None:
        if entry is None:
            self.exit()
            return
        with self.suspend():
            run_entry(self.env, entry)
        self._open()


def run_library(env: Home) -> int:
    """Open the list of every task and image (`hashpass work`)."""
    LibraryApp(env).run()
    return 0
