"""
Full-screen Textual TUI for the student pool client (the `hashpass` menu).

Replaces the line-oriented `_render_pool_menu`: a left-hand blocks/tasks list, a right-hand
task detail card, one **Enter** to run a task, live parallel background downloads with per-task
state (ожидает / грузится / готово / ошибка), and clean statuses (решено / зачтено) instead
of the old `★` glyph. Hidden tasks (locked block or per-task hidden) render as "№N · закрыто"
without the ref -- the student sees the slot but not what it is.

If the runtime `textual` package isn't installed, `cli.cmd_pool_home` falls back to the plain
text menu; `run_tui` never raises for that path -- it raises `ImportError` at the top of the
module before any function is called.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, ListItem, ListView, Static

from hashpass.imagestore.store import ImageStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest

if TYPE_CHECKING:
    from hashpass.cli import Home

_DOWN_WORKERS = 6            # parallel background downloads
_POLL_INTERVAL = 0.4         # UI refresh cadence (seconds); state is polled, not pushed


@dataclass
class TaskRow:
    """One live row in the TUI (server-supplied + local download + credit state)."""

    ref: str
    number: int
    block: str
    available: bool
    digest: str
    server: str | None = None       # "passed" / "failed" / None (pool verdict)
    local: bool = False             # solved on this machine (offline mark)
    state: str = "ожидает"          # local download state: ожидает / грузится / готово / ошибка
    hidden: bool = False            # locked to the student: block closed OR per-task hidden

    @property
    def runnable(self) -> bool:
        """True when the student can Enter into it (visible and downloaded)."""
        return not self.hidden and self.state == "готово"

    def status_label(self) -> str:
        """One-line right-hand-side label with server verdict + local download progress."""
        if self.hidden:
            return "закрыто"
        if self.server == "passed":
            head = "зачтено"
        elif self.local:
            head = "решено"
        else:
            head = "не начато"
        if self.state == "готово":
            return head
        return f"{head} · {self.state}"


class _TaskItem(ListItem):
    """A ListView item that remembers which TaskRow it renders (or None for a block header)."""

    def __init__(self, label: Static, row: TaskRow | None) -> None:
        super().__init__(label)
        self.row = row


class PoolTUI(App):
    """Full-screen blocks/tasks tree + live downloads + one-Enter run."""

    CSS = """
    Screen { layout: horizontal; }
    #tasks { width: 44%; border-right: heavy $accent; padding: 0; }
    #detail { padding: 1 2; }
    ListView { padding: 0; }
    ListItem { padding: 0 1; height: 1; }
    ListItem.-block { color: $accent; text-style: bold; padding-top: 1; }
    ListItem.-hidden { color: $text-muted; }
    ListItem.-done { color: $success; }
    ListItem.-loading { color: $warning; }
    ListItem.-error { color: $error; }
    .detail-title { text-style: bold; padding-bottom: 1; }
    .detail-pill { color: $accent; }
    """

    BINDINGS = [   # noqa: RUF012  (Textual expects a plain class-level list)
        Binding("q", "quit", "Выход"),
        Binding("r", "refresh", "Обновить"),
        Binding("s", "resync", "Самопроверка"),
        Binding("enter", "run", "Запустить"),
    ]

    def __init__(self, env: Home, url: str, user: str, token: str) -> None:
        """Store credentials and hand-off env; start with an empty rows list."""
        super().__init__()
        self.env = env
        self.url = url
        self.user = user
        self.token = token
        self.client = RemoteRegistry(url)
        self.store = ImageStore(env.images)
        self.rows: list[TaskRow] = []
        self._rows_lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = None

    # -- lifecycle --------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Header + horizontal split (tasks | detail) + footer with keybinds."""
        yield Header(show_clock=False)
        with Horizontal():
            yield ListView(id="tasks")
            yield Static("Выберите задание из списка слева.\n\n[dim]q — выход · r — обновить · s — самопроверка · Enter — запустить[/]",
                         id="detail")
        yield Footer()

    def on_mount(self) -> None:
        """Load the catalog and start the refresh timer -- do NOT auto-pull anything."""
        self.title = f"hashpass · {self.user}"
        self._reload_catalog()
        # a lazy pool: created only if the student actually asks to run an unready task
        self._pool = ThreadPoolExecutor(max_workers=_DOWN_WORKERS)
        self.set_interval(_POLL_INTERVAL, self._paint)

    def on_unmount(self) -> None:
        """Stop background workers on quit."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    # -- data -------------------------------------------------------------

    def _reload_catalog(self) -> None:
        """Fetch catalog + progress + local-solved, then rebuild `self.rows`."""
        from hashpass.cli import (  # noqa: PLC0415  (avoid cycle at module load)
            load_solved,
            task_dir,
        )
        try:
            entries = self.client.catalog(token=self.token)
        except Exception:                                  # noqa: BLE001 (offline / network -- render empty)
            entries = []
        solved = load_solved(self.env)
        try:
            mine = self.client.progress(token=self.token).get(self.user, {})
        except Exception:                                  # noqa: BLE001
            mine = {}
        rows: list[TaskRow] = []
        for e in entries:
            ref = str(e["ref"])
            hidden = not e.get("available", True)
            digest = str(e.get("digest", ""))
            ready = False
            if self.store.exists(ref):
                tdir = task_dir(ref, self.store)
                ready = tdir.exists() and task_digest(tdir) == digest
            server_status = None
            if isinstance(mine.get(ref), dict):
                server_status = str(mine[ref].get("status") or "") or None
            rows.append(TaskRow(
                ref=ref, number=int(e.get("number") or 0), block=str(e.get("block_name", "")),
                available=bool(e.get("available", True)), digest=digest,
                server=server_status, local=ref in solved,
                state="готово" if ready else "ожидает", hidden=hidden))
        with self._rows_lock:
            self.rows = rows
        self._paint()

    def _download_row(self, row: TaskRow) -> None:
        """Pull the row's image closure + task bundle; update `row.state` transitions."""
        from hashpass.cli import task_dir  # noqa: PLC0415
        try:
            row.state = "грузится"
            self.client.pull_many([row.ref], self.store, workers=2)
            if self.store.exists(row.ref):
                tdir = task_dir(row.ref, self.store)
                if not tdir.exists() or task_digest(tdir) != row.digest:
                    self.client.pull_task(row.ref, tdir, token=self.token)
                row.state = "готово"
            else:
                row.state = "ошибка"
        except Exception:                                  # noqa: BLE001
            row.state = "ошибка"

    # -- render -----------------------------------------------------------

    def _paint(self) -> None:
        """Rebuild the left ListView from `self.rows`, preserving the highlighted index."""
        lv = self.query_one("#tasks", ListView)
        cur = lv.index
        lv.clear()
        last_block: str | None = None
        with self._rows_lock:
            rows_snapshot = list(self.rows)
        if not rows_snapshot:
            lv.append(_TaskItem(Static("В пуле пока нет заданий."), None))
            return
        for row in rows_snapshot:
            if row.block != last_block:
                last_block = row.block
                header = _TaskItem(Static(row.block or "Задания"), None)
                header.disabled = True
                header.add_class("-block")
                lv.append(header)
            if row.hidden:
                label = Static(f"№{row.number} · закрыто")
                item = _TaskItem(label, row)
                item.add_class("-hidden")
            else:
                label = Static(f"№{row.number} · {row.ref}    {row.status_label()}")
                item = _TaskItem(label, row)
                if row.state == "ошибка":
                    item.add_class("-error")
                elif row.state in {"грузится", "ожидает"}:
                    item.add_class("-loading")
                elif row.server == "passed" or row.local:
                    item.add_class("-done")
            lv.append(item)
        if cur is not None and cur < len(lv):
            lv.index = cur

    def _row_of(self, item: _TaskItem | None) -> TaskRow | None:
        return item.row if isinstance(item, _TaskItem) else None

    def _update_detail(self, row: TaskRow | None) -> None:
        detail = self.query_one("#detail", Static)
        if row is None:
            detail.update("Выберите задание из списка слева.\n\n"
                          "[dim]q — выход · r — обновить · s — самопроверка · Enter — запустить[/]")
            return
        if row.hidden:
            detail.update(f"[b]№{row.number}[/b]\n\n[dim]Задание закрыто преподавателем.[/dim]")
            return
        state_line = f"Загрузка: [b]{row.state}[/]"
        server_line = ""
        if row.server == "passed":
            server_line = "\nПул: [green]зачтено[/]"
        elif row.server == "failed":
            server_line = "\nПул: [yellow]не зачтено[/]"
        local_line = "\nЛокально: [green]решено[/]" if row.local else ""
        detail.update(
            f"[b]№{row.number}[/b]  [dim]{row.block or 'Задания'}[/]\n"
            f"[b cyan]{row.ref}[/]\n\n"
            f"{state_line}{server_line}{local_line}\n\n"
            "[dim]Enter — запустить · q — выход · r — обновить[/]")

    # -- events -----------------------------------------------------------

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Highlighted item -> refresh the right-hand detail panel."""
        self._update_detail(self._row_of(event.item))

    def action_refresh(self) -> None:
        """Reload the catalog. Do not touch downloads -- those wait for Enter on a row."""
        self._reload_catalog()

    def action_resync(self) -> None:
        """Re-submit tasks solved locally but not credited on the server (self-check)."""
        from hashpass.cli import Io, _resync  # noqa: PLC0415
        buf: list[str] = []
        _resync(self.env, self.url, self.user, self.token,
                Io(read=lambda _p: None, write=buf.append, clock=time.strftime))
        self._flash("\n".join(buf).strip())
        self._reload_catalog()

    def action_run(self) -> None:
        """Enter: download this task on-demand if needed (visible progress), then run it."""
        lv = self.query_one("#tasks", ListView)
        item = lv.highlighted_child
        row = self._row_of(item)
        if row is None or row.hidden:
            self._flash("Выберите доступное задание.")
            return
        if row.state != "готово":
            # download only THIS task (and its closure), never the whole catalog
            self._flash(f"Загружаю {row.ref}…  (прогресс на строке слева)")
            self._download_row(row)
            if row.state != "готово":
                self._flash(f"Не удалось загрузить {row.ref}: {row.state}")
                return
        from hashpass.cli import cmd_pool_run  # noqa: PLC0415
        with self.suspend():
            cmd_pool_run(self.env, row.ref)
        self._reload_catalog()

    def _flash(self, msg: str) -> None:
        """Show a one-shot status message in the detail pane (auto-clears on next highlight)."""
        self.query_one("#detail", Static).update(msg or "")


def run_tui(env: Home, url: str, user: str, token: str) -> int:
    """Enter the Textual app; on quit, return 0. Errors bubble up so `cmd_pool_home` can fall back."""
    PoolTUI(env, url, user, token).run()
    return 0
