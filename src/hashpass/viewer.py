"""
The source viewer in hashpass: a task's files as its author wrote them (authors and admins).

User, 2026-10-14: «просмотрщик файлов сразу хочу встроить, чтобы можно было всё смотреть,
папки, Taskfile и другие» + «давай не архивом, давай все-таки все файлы». The pool keeps a task's
sources as files (`GET /source/<ref>` lists them, `?path=` gives one); the viewer shows the tree
on the left and the chosen file on the right. A pool from before `/source` has only the Taskfile
attachment -- then the tree is that one file.
"""
from __future__ import annotations

import urllib.error
from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static, Tree

if TYPE_CHECKING:
    from textual.app import ComposeResult

Fetch = Callable[[str], bytes]


def listing_or_taskfile(client, ref: str, token: str) -> tuple[list[dict[str, object]], Fetch]:
    """Return (files, fetch): the pool's source tree, or -- on an old pool -- just the Taskfile."""
    try:
        files = client.source_listing(ref, token=token)
        return files, lambda path: client.source_file(ref, path, token=token)
    except urllib.error.HTTPError as exc:
        if exc.code not in (HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED):
            raise
    name, _, version = ref.partition(":")
    taskfile = client.get_attachment(name, version or "latest", "Taskfile", token=token)
    return ([{"path": "Taskfile", "size": len(taskfile), "dir": False}],
            lambda _path: taskfile)


def _shown(blob: bytes) -> str:
    """Decode a file as text, or say that it is binary."""
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return f"двоичный файл, {len(blob)} байт"


class SourceViewer(Screen):
    """Tree of a task's files + the chosen file's text. Esc/q -- back to the catalog."""

    CSS = """
    #src-tree { width: 40%; border-right: solid $accent; }
    #src-body { padding: 0 1; }
    """
    BINDINGS = [Binding("escape,q,Q,й,Й", "app.pop_screen", "Назад")]   # noqa: RUF012

    def __init__(self, ref: str, files: list[dict[str, object]], fetch: Fetch) -> None:
        """Show `files` of `ref`; `fetch(path)` returns a file's bytes (cached once read)."""
        super().__init__()
        self.ref = ref
        self.files = files
        self._fetch = fetch
        self._cache: dict[str, str] = {}
        self._text = ""

    def compose(self) -> ComposeResult:
        """Build the tree on the left, the file on the right."""
        tree: Tree[str] = Tree(self.ref, id="src-tree")
        tree.show_root = True
        nodes = {"": tree.root}
        for f in self.files:
            path = str(f["path"])
            parent = nodes.get(path.rsplit("/", 1)[0] if "/" in path else "", tree.root)
            label = path.rsplit("/", 1)[-1]
            if f.get("dir"):
                nodes[path] = parent.add(f"{label}/", data=path, expand=True)
            else:
                parent.add_leaf(label, data=path)
        tree.root.expand()
        with Horizontal():
            yield tree
            with VerticalScroll():
                yield Static("Выбери файл слева.", id="src-body")
        yield Footer()

    def shown_paths(self) -> list[str]:
        """Return every path the tree shows, in order (for tests)."""
        return [str(f["path"]) for f in self.files]

    def shown_text(self) -> str:
        """Return the text currently shown on the right (for tests)."""
        return self._text

    def open_path(self, path: str) -> None:
        """Show one file on the right."""
        if path not in self._cache:
            try:
                self._cache[path] = _shown(self._fetch(path))
            except Exception as exc:                       # noqa: BLE001  (offline, 404 …)
                self._cache[path] = f"не удалось открыть: {exc}"
        self._text = self._cache[path]
        self.query_one("#src-body", Static).update(Text(f"{path}\n\n{self._text}"))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter on a file opens it (a directory just folds)."""
        path = event.node.data
        if isinstance(path, str) and not event.node.allow_expand:
            self.open_path(path)
