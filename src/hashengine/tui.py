"""
The author's work screen: `hashengine` with no arguments (spec 2026-10-21 §10).

Two tabs, like `docker images` and a registry browser: «Локально» -- images on this machine
(run without credit, push, delete, sources); «Пул» -- images on the pool (pull, run, tag,
delete a revision, visibility, fork). Courses, blocks and moderation live on the web.
"""
from __future__ import annotations

import contextlib
import io as _io
import sys
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

from rich.markup import escape
from textual import work
from textual.app import App
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, TabbedContent, TabPane, Tree

from hashpass.course_screen import AskScreen
from hashpass.imagestore.store import ImageStore
from hashpass.registry.revisions import parse_version
from hashpass.viewer import SourceViewer, listing_or_taskfile

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from hashpass.cli import Home


class ConfirmDelete(ModalScreen[bool]):
    """y -- yes, anything else -- no."""

    BINDINGS = [Binding("y,Y,д,Д,н,Н", "answer(True)", "Да"),  # noqa: RUF012
                Binding("n,N,т,Т,escape", "answer(False)", "Нет")]

    def __init__(self, question: str) -> None:
        """Remember the question."""
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        """Build the question."""
        with Vertical(id="dialog"):
            yield Label(self.question)
            yield Label("[b]y[/] — да, [b]n[/] — нет")

    def action_answer(self, yes: bool) -> None:  # noqa: FBT001
        """Close with the answer."""
        self.dismiss(yes)


def _local_files(taskfile: str | None) -> tuple[list[dict[str, object]], object]:
    """Return the task directory a local build came from, as the source viewer wants it."""
    root = Path(taskfile).parent if taskfile else None
    if root is None or not root.is_dir():
        return [], lambda _p: b""
    files = [{"path": p.relative_to(root).as_posix(), "size": 0 if p.is_dir() else p.stat().st_size,
              "dir": p.is_dir()} for p in sorted(root.rglob("*")) if "__pycache__" not in p.parts]
    return files, lambda path: (root / path).read_bytes()


class EngineTUI(App):
    """Local images and pool images, side by side in two tabs."""

    CSS = """
    ConfirmDelete, AskScreen { align: center middle; }
    #dialog { width: 80; height: auto; padding: 1 2; border: thick $accent; background: $panel; }
    Tree { padding: 0 1; }
    #filter { margin: 0 1; display: none; }
    """
    BINDINGS = [  # noqa: RUF012
        Binding("q,Q,й,Й", "quit", "Выход"),
        Binding("tab", "switch", "Локально/Пул", priority=True),
        Binding("r,R,к,К", "refresh", "Обновить"),
        # Enter on a row runs it (the tree's NodeSelected); not an app binding, so Enter still
        # submits the tag / fork / filter fields
        Binding("enter", "run", "Запустить"),
        Binding("p,P,з,З", "push", "Отправить"),
        Binding("l,L,д,Д", "pull", "Скачать"),
        Binding("t,T,е,Е", "tag", "Тег"),
        Binding("d,D,в,В,delete", "delete", "Удалить"),
        Binding("s,S,ы,Ы", "visibility", "Видимость"),
        Binding("f,F,а,А", "fork", "Форк"),
        Binding("v,V,м,М", "view", "Исходники"),
        Binding("slash", "filter", "Поиск"),
    ]

    def __init__(self, env: Home, url: str, user: str, token: str, client: object | None = None) -> None:
        """Bind to the author's home and pool (client: injected in tests)."""
        super().__init__()
        from hashpass.registry.remote import RemoteRegistry  # noqa: PLC0415
        self.env, self.url, self.user, self.token = env, url, user, token
        self.client = client or (RemoteRegistry(url, token=token) if url else None)
        self.store = ImageStore(env.images)
        self.pool_rows: list[dict[str, object]] = []
        self.query_text = ""

    # -- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Header, a filter line, two tabs, footer."""
        yield Header()
        yield Input(placeholder="фильтр по имени (Esc — убрать)", id="filter")
        with TabbedContent(id="tabs"):
            with TabPane("Локально", id="local"):
                yield Tree("Локально", id="local-tree")
            with TabPane("Пул", id="pool"):
                yield Tree("Пул", id="pool-tree")
        yield Footer()

    def on_mount(self) -> None:
        """Fill both tabs."""
        self.title = "hashengine"
        self.sub_title = f"{self.user or 'не вошли'} · {self.url or 'пул не задан'}"
        for tree_id in ("#local-tree", "#pool-tree"):
            self.query_one(tree_id, Tree).show_root = False
        self._paint_local()
        self._load_pool()

    @property
    def on_pool(self) -> bool:
        return self.query_one("#tabs", TabbedContent).active == "pool"

    def action_switch(self) -> None:
        """Tab: the other tab."""
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "local" if tabs.active == "pool" else "pool"
        self.query_one(f"#{tabs.active}-tree", Tree).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show each key where it does something."""
        local_only, pool_only = {"push"}, {"pull", "tag", "visibility", "fork"}
        if action in local_only and self.on_pool:
            return False
        if action in pool_only and not self.on_pool:
            return False
        return super().check_action(action, parameters)

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        """Refresh the footer for the active tab."""
        self.refresh_bindings()

    # -- data -------------------------------------------------------------------

    def _matches(self, ref: str) -> bool:
        return not self.query_text or self.query_text.casefold() in ref.casefold()

    def _paint_local(self) -> None:
        tree = self.query_one("#local-tree", Tree)
        tree.clear()
        repos: dict[str, list[str]] = {}
        for ref in self.store.list():
            if self._matches(ref):
                repos.setdefault(ref.partition(":")[0], []).append(ref)
        for repo, refs in sorted(repos.items()):
            node = tree.root.add(f"[b]{escape(repo)}[/]", expand=True)
            for ref in refs:
                img = self.store.get(ref)
                task = (img.layer.parent / "task").exists()
                _tag, n, _ = parse_version(img.version)
                kind = "задание" if task else "образ"
                where = f"ревизия пула v{n}" if n else "своя сборка"
                node.add_leaf(f"{escape(ref)}  [dim]{kind} · {where}[/]", data={"ref": ref, "local": True})
        if not repos:
            tree.root.add_leaf("[dim]локальных образов нет — hashengine build <Taskfile>[/]")

    @work(thread=True, exclusive=True, group="pool")
    def _load_pool(self) -> None:
        rows: list[dict[str, object]] = []
        note = ""
        if self.client is None:
            note = "пул не задан — hashengine login <адрес>"
        else:
            try:
                rows = list(self.client.pool_images(token=self.token))
            except Exception as exc:                       # noqa: BLE001  (offline / signed out)
                note = f"пул недоступен: {exc}"
        self.call_from_thread(self._paint_pool, rows, note)

    def _paint_pool(self, rows: list[dict[str, object]], note: str = "") -> None:
        self.pool_rows = rows
        tree = self.query_one("#pool-tree", Tree)
        tree.clear()
        if note:
            tree.root.add_leaf(f"[yellow]{escape(note)}[/]")
        repos: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            if self._matches(str(row["ref"])):
                repos.setdefault(str(row.get("repo") or str(row["ref"]).partition(":")[0]), []).append(row)
        for repo, items in sorted(repos.items()):
            owner = repo.partition("/")[0] == self.user
            node = tree.root.add(f"[b]{escape(repo)}[/]" + ("  [green]моё[/]" if owner else ""), expand=owner)
            for row in sorted(items, key=lambda r: (str(r.get("tag")), -(int(r.get("n") or 0)))):
                latest = "  [cyan]последняя[/]" if row.get("latest") else ""
                kind = "задание" if row.get("kind") == "task" else "образ"
                node.add_leaf(f"{escape(str(row['ref']))}  [dim]{kind}[/]{latest}",
                              data={"ref": str(row["ref"]), "local": False})

    def _cursor(self) -> dict[str, object] | None:
        tree = self.query_one("#pool-tree" if self.on_pool else "#local-tree", Tree)
        node = tree.cursor_node
        return node.data if node is not None and isinstance(node.data, dict) else None

    def action_refresh(self) -> None:
        """r: reread both tabs."""
        self._paint_local()
        self._load_pool()

    # -- actions ----------------------------------------------------------------

    def _cli(self, fn_name: str, *args: object, **kwargs: object) -> str:
        """Run one cli command, capturing what it prints; return the text (errors included)."""
        from hashpass import cli  # noqa: PLC0415
        out = _io.StringIO()
        io = cli.Io(read=lambda _p: "", write=out.write, clock=lambda: "")
        old = sys.stdout
        sys.stdout = out
        try:
            getattr(cli, fn_name)(self.env, *args, io=io, **kwargs)
        except Exception as exc:                            # noqa: BLE001  (shown, not raised)
            out.write(str(exc))
        finally:
            sys.stdout = old
        return out.getvalue().strip()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter on a row: run it; on a repository: fold or unfold it."""
        if isinstance(event.node.data, dict):
            self.action_run()
        else:
            event.node.toggle()

    def action_run(self) -> None:
        """Run the image or task under the cursor as its author -- no credit."""
        row = self._cursor()
        if row is None:
            return
        from hashpass import cli  # noqa: PLC0415
        with self.suspend():
            sys.stdout.write("\x1b[2J\x1b[H")
            cli.cmd_engine_run(self.env, str(row["ref"]), self.url or None)
        self.action_refresh()

    def action_push(self) -> None:
        """p: send a local build to the pool as a new revision."""
        row = self._cursor()
        if row is None or not row["local"]:
            return
        ref = str(row["ref"])
        if parse_version(ref.partition(":")[2])[1] is not None:
            self.notify("это ревизия, скачанная с пула — отправлять нечего", timeout=4)
            return
        self.notify(f"отправляю {ref}…", timeout=3)
        self._push(ref)

    @work(thread=True, group="push")
    def _push(self, ref: str) -> None:
        text = self._cli("cmd_push", ref, self.url or None)
        self.call_from_thread(self.notify, text or "готово", timeout=8)
        self.call_from_thread(self._load_pool)

    def action_pull(self) -> None:
        """l: download a pool revision to this machine."""
        row = self._cursor()
        if row is None or row["local"] or self.client is None:
            return
        ref = str(row["ref"])
        try:
            self.client.pull(ref, self.store)
        except Exception as exc:                            # noqa: BLE001
            self.notify(f"{ref}: {exc}", severity="error", timeout=6)
            return
        self.notify(f"скачано: {ref}", timeout=4)
        self._paint_local()

    def action_tag(self) -> None:
        """t: tag one of your revisions on the pool."""
        row = self._cursor()
        if row is None or row["local"] or self.client is None:
            return
        ref = str(row["ref"])

        def done(tag: str | None) -> None:
            if not tag:
                return
            try:
                made = self.client.tag(ref, tag, token=self.token)
            except Exception as exc:                        # noqa: BLE001
                self.notify(_reason(exc), severity="error", timeout=6)
                return
            self.notify(f"тег навешен: {made}", timeout=4)
            self._load_pool()
        self.push_screen(AskScreen(f"Новый тег для [b]{escape(ref)}[/]:", "например, stable"), callback=done)

    def action_delete(self) -> None:
        """d: delete -- a local copy here, or your revision on the pool (may need the admin)."""
        row = self._cursor()
        if row is None:
            return
        ref = str(row["ref"])
        where = "с этой машины" if row["local"] else "с пула"

        def done(yes: bool | None) -> None:  # noqa: FBT001
            if not yes:
                return
            if row["local"]:
                self.store.remove(ref)
                self._paint_local()
                self.notify(f"удалено локально: {ref}", timeout=4)
                return
            text = self._cli("cmd_rm", ref, self.url or None)
            self.notify(text or "готово", timeout=8)
            self._load_pool()
        self.push_screen(ConfirmDelete(f"Удалить [b]{escape(ref)}[/] {where}?"), callback=done)

    def action_visibility(self) -> None:
        """s: switch your repository between public and private."""
        row = self._cursor()
        if row is None or row["local"] or self.client is None:
            return
        repo = str(row["ref"]).partition(":")[0]
        try:
            info = self.client.revisions(repo, token=self.token)
            now = "private" if info.get("visibility") == "public" else "public"
            self.client.repo_settings(repo, token=self.token, visibility=now)
        except Exception as exc:                            # noqa: BLE001
            self.notify(_reason(exc), severity="error", timeout=8)
            return
        self.notify(f"{repo}: {'приватный' if now == 'private' else 'публичный'}", timeout=4)

    def action_fork(self) -> None:
        """f: fork someone's revision into your namespace."""
        row = self._cursor()
        if row is None or row["local"] or self.client is None:
            return
        ref = str(row["ref"])
        short = ref.partition(":")[0].rpartition("/")[2]

        def done(name: str | None) -> None:
            if name is None:
                return
            try:
                made = self.client.fork(ref, f"{self.user}/{name or short}", token=self.token)
            except Exception as exc:                        # noqa: BLE001
                self.notify(_reason(exc), severity="error", timeout=6)
                return
            self.notify(f"форк: {made} — исходники: hashengine source {made}", timeout=8)
            self._load_pool()
        self.push_screen(AskScreen(f"Форк [b]{escape(ref)}[/] — имя (Enter — {short}):", short), callback=done)

    def action_view(self) -> None:
        """v: the sources -- the local task directory, or the pool's copy."""
        row = self._cursor()
        if row is None:
            return
        ref = str(row["ref"])
        if row["local"]:
            files, fetch = _local_files(self.store.get(ref).taskfile_path)
        else:
            try:
                files, fetch = listing_or_taskfile(self.client, ref, self.token)
            except urllib.error.HTTPError as exc:
                text = ("у этого образа нет исходников на пуле" if exc.code == 404  # noqa: PLR2004
                        else f"исходники не открылись: {_reason(exc)}")
                self.notify(text, severity="warning", timeout=6)
                return
            except Exception as exc:                        # noqa: BLE001
                self.notify(f"исходники не открылись: {_reason(exc)}", severity="error", timeout=6)
                return
        if not files:
            self.notify("исходников нет", timeout=4)
            return
        self.push_screen(SourceViewer(ref, files, fetch))

    def action_filter(self) -> None:
        """/: filter both tabs by name."""
        box = self.query_one("#filter", Input)
        box.display = True
        box.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refilter as the author types."""
        self.query_text = event.value.strip()
        self._paint_local()
        self._paint_pool(self.pool_rows)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter in the filter: back to the list."""
        self.query_one("#pool-tree" if self.on_pool else "#local-tree", Tree).focus()


def _reason(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        with contextlib.suppress(Exception):
            import json  # noqa: PLC0415
            return str(json.loads(exc.read()).get("error") or exc)
    return str(exc)


def run_engine_tui(env: Home) -> int:
    """Open the work screen for the configured pool (signed in or not)."""
    from hashpass.account import current  # noqa: PLC0415
    url, user, token = current(env)
    EngineTUI(env, url, user, token).run()
    return 0
