"""
Full-screen Textual TUI for the student pool client (the `hashpass` menu).

Left: a `Tree` of blocks -> tasks -- arrows navigate, Enter on a leaf runs it,
Enter on a block collapses/expands it (native Tree behaviour, nothing to relearn).
Right: a splash card on empty selection, a rich task-detail card on a highlighted
task. Statuses are words (решено / зачтено / не начато / грузится). Hidden tasks
are not sent to students at all; an author/admin (`preview` from the pool) sees
the ref with a «скрыто» badge and can run it. No task numbers: order only. Bindings honour both English AND Russian keyboard layouts, so
q/й, r/к, s/ы all work regardless of the OS layout.

If the runtime `textual` package isn't installed, `cli.cmd_pool_home` falls back
to the plain text menu; `run_tui` never raises for that path -- the ImportError
happens on this module's own import, before any function is called.
"""
from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, Static, Tree

from hashpass.imagestore.store import ImageStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest
from hashpass.treekeys import VIM_BINDINGS, vim_walk
from hashpass.viewer import SourceViewer, listing_or_taskfile

if TYPE_CHECKING:
    from hashpass.cli import Home

_DOWN_WORKERS = 4            # layers of ONE task downloaded in parallel (tasks go one by one)
_TICK = 0.2                  # seconds between repaints of a running download (only when dirty)
_BAR = 24                    # width of a layer's progress bar in the downloads panel
_TASK_LAYER = "задание (проверка)"   # pseudo-layer: the task bundle pulled after the images


def _mb(n: int) -> str:
    return f"{n / (1 << 20):.1f}"


def _bar(frac: float, width: int = _BAR) -> str:
    full = max(0, min(width, round(frac * width)))
    return "█" * full + "░" * (width - full)


@dataclass
class LayerBar:
    """One layer in the downloads panel, like a `docker pull` line."""

    ref: str
    done: int = 0
    total: int | None = None
    state: str = "ждёт"             # ждёт / качается / готово / ошибка

    def line(self, width: int) -> str:
        """Rich-markup line: name, bar, percent and megabytes (or a word while not streaming)."""
        name = escape(self.ref.ljust(width))
        if self.state == "готово":
            return f"  {name}  [green]{_bar(1.0)}  готово[/]"
        if self.state == "ошибка":
            return f"  {name}  [red]ошибка[/]"
        if self.state == "ждёт" or not self.total:
            got = f"  {_mb(self.done)} МБ" if self.done else ""
            return f"  {name}  [dim]{_bar(0.0)}  {self.state}{got}[/]"
        frac = self.done / self.total
        return (f"  {name}  [cyan]{_bar(frac)}[/] {frac * 100:3.0f}%  "
                f"{_mb(self.done)}/{_mb(self.total)} МБ")

def _read_line(prompt: str) -> str | None:
    """Read one line from the suspended terminal (the after-task choice); None at EOF."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):     # Ctrl-C here means «в меню», not «kill the TUI»
        return None


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
    state: str = "ожидает"          # local download: ожидает / в очереди / грузится / готово / ошибка
    progress: float = 0.0           # 0..1 while грузится (all layers together)
    hidden: bool = False            # locked to the student: block closed OR per-task hidden
    preview: bool = False           # locked for students, but this viewer (author/admin) may run it
    task_hidden: bool = False       # the task's own «скрыто» flag (staff toggle it with h)
    error: str = ""                 # why the last download failed (shown next to «ошибка загрузки»)
    block_id: str = ""
    block_open: bool = True         # the block is open to students (staff toggle it with o)
    moderation: str = "approved"    # pending / approved / rejected (the pool's moderation)
    pending_update: bool = False    # approved earlier; a newer push waits for approval
    reason: str = ""                # why it was rejected
    expires_at: float | None = None  # when a rejected task is deleted (unix)
    owner: str = ""                 # the author (ref namespace)

    def moderation_badge(self) -> str:
        """Moderation state for the staff: на проверке / обновление на проверке / отклонено …."""
        if self.moderation == "rejected":
            why = f": {escape(self.reason)}" if self.reason else ""
            days = ""
            if self.expires_at is not None:
                left = max(0, -(-int(self.expires_at - time.time()) // 86400))   # ceil, in days
                days = f" · удалится через {left} дн."
            return f"   [red]· отклонено{why}{days}[/]"
        if self.pending_update:
            return "   [yellow]· обновление на проверке[/]"
        if self.moderation == "pending":
            return "   [yellow]· на проверке[/]"
        return ""

    def status_label(self) -> str:
        """One-line status without Rich markup (used by tests / plain-text callers)."""
        if self.hidden:
            return "закрыто"
        parts = []
        parts.append("решено" if self.local else "не решено")
        parts.append("зачтено" if self.server == "passed" else "не зачтено")
        return " · ".join([*parts, self.download_word()])

    def download_word(self) -> str:
        """Plain download status: загружено / не загружено / в очереди / грузится N% / ошибка."""
        if self.state == "готово":
            return "загружено"
        if self.state == "грузится":
            return f"грузится {self.progress * 100:.0f}%"
        if self.state == "ошибка":
            return "ошибка загрузки"
        return "в очереди" if self.state == "в очереди" else "не загружено"

    def tree_label(self) -> str:
        """
        Two badges -- `решено` (local, this machine) and `зачтено` (server credited).

        The user pointed out these are distinct states: a task can be solved locally
        (marked in `solved.json`) but still not credited on the pool (network fail,
        digest mismatch, teacher-side digest bump), and, less often, the pool can
        show `зачтено` without a local mark (done on another machine). Show both.
        """
        if self.hidden:
            return "[dim]закрыто[/]"
        local_dot = "[green]●[/] решено" if self.local else "[dim]○ не решено[/]"
        server_dot = "[green]●[/] зачтено" if self.server == "passed" else "[dim]○ не зачтено[/]"
        if self.state == "готово":
            down = "[green]●[/] загружено"
        elif self.state == "грузится":
            down = f"[cyan]{_bar(self.progress, 10)} {self.progress * 100:3.0f}%[/]"
        elif self.state == "в очереди":
            down = "[cyan]◌ в очереди[/]"
        elif self.state == "ошибка":
            why = f" — {escape(self.error)}" if self.error else ""
            down = f"[red]✗ ошибка загрузки{why}[/]"
        else:
            down = "[dim]○ не загружено[/]"
        tail = f"   {local_dot}   {server_dot}   {down}"
        badge = self.moderation_badge()
        if self.preview and not badge:
            tail += "   [yellow]· скрыто[/]"
        return f"{self.ref}{tail}{badge}"


class ReasonScreen(ModalScreen[str | None]):
    """Ask the admin why a task is rejected (Enter -- with or without a reason, Esc -- cancel)."""

    BINDINGS = [Binding("escape", "cancel", "Отмена")]   # noqa: RUF012

    def __init__(self, ref: str) -> None:
        """Remember which task is being rejected."""
        super().__init__()
        self.ref = ref

    def compose(self) -> ComposeResult:
        """Build a label and one input line."""
        with Vertical(id="dialog"):
            yield Label(f"Отклонить [b]{escape(self.ref)}[/]? Причина (необязательно), Enter — отклонить:")
            yield Input(placeholder="что поправить", id="reason")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter: reject with what was typed."""
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        """Esc: do not reject."""
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no question (y/д -- yes; n/н/Esc -- no)."""

    BINDINGS = [   # noqa: RUF012
        Binding("y,Y,д,Д,н,Н", "answer(True)", "Да"),
        Binding("n,N,т,Т,escape", "answer(False)", "Нет"),
    ]

    def __init__(self, question: str) -> None:
        """Remember the question."""
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        """Build the question and the keys."""
        with Vertical(id="dialog"):
            yield Label(self.question)
            yield Label("[b]y[/] — да, [b]n[/] — нет")

    def action_answer(self, yes: bool) -> None:  # noqa: FBT001
        """Close with the answer."""
        self.dismiss(yes)


class PoolTUI(App):
    """Full-screen blocks/tasks tree + a rich detail card + one-Enter run."""

    CSS = """
    Screen { background: $surface; }
    ReasonScreen, ConfirmScreen { align: center middle; }
    #dialog { width: 80; height: auto; padding: 1 2; border: thick $accent; background: $panel; }
    Tree { padding: 1 2; background: $surface; }
    Tree > .tree--cursor { background: $accent 40%; color: $text; }
    Tree > .tree--highlight-line { background: $accent 20%; }
    #downloads { height: auto; max-height: 14; padding: 0 2; border-top: solid $accent;
                 display: none; }
    """

    # Textual binds against the character, not the physical key -- a Russian layout
    # would map Q/R/S to й/к/ы. Bind both plus uppercase; Enter needs no localisation.
    BINDINGS = [   # noqa: RUF012  (Textual expects a plain class-level list)
        Binding("q,Q,й,Й", "quit", "Выход"),
        Binding("r,R,к,К", "refresh", "Обновить"),
        Binding("s,S,ы,Ы", "resync", "Самопроверка"),
        # Catalog editing for staff (shown only to them, see check_action): the same rights as
        # the web catalog -- an author hides/shows its own tasks, the admin also moves them.
        Binding("x,X,ч,Ч", "toggle_hidden", "Скрыть/показать"),
        Binding("o,O,щ,Щ", "toggle_block", "Открыть/закрыть блок"),
        # priority: the Tree would take Shift+arrows as plain cursor moves otherwise
        Binding("shift+up", "move(-1)", "Выше", priority=True),
        Binding("shift+down", "move(1)", "Ниже", priority=True),
        Binding("K,Л", "move(-1)", "Выше", show=False),
        Binding("J,О", "move(1)", "Ниже", show=False),
        # vim keys (user, 2026-10-15: «клавиш как в vim hjkl как минимум»): j/k -- down/up,
        # h -- to the block / fold it, l -- unfold / into it / run the task, g/G -- top/bottom.
        *VIM_BINDINGS,
        # Moderation (spec 2026-10-14): the admin approves / rejects, an author deletes own tasks.
        Binding("a,A,ф,Ф", "approve", "Одобрить"),
        Binding("n,N,т,Т", "reject", "Отклонить"),
        Binding("delete", "delete_task", "Удалить"),
        Binding("z,Z,я,Я", "toggle_rejected", "Отклонённые"),
        Binding("v,V,м,М", "view", "Исходники"),
    ]

    def __init__(self, env: Home, url: str, user: str, token: str) -> None:
        """Wire creds + env; the rows list stays empty until on_mount reloads."""
        super().__init__()
        self.env = env
        self.url = url
        self.user = user
        self.token = token
        self.client = RemoteRegistry(url, token=token)
        self.store = ImageStore(env.images)
        self.rows: list[TaskRow] = []
        self._load_error: str | None = None    # why the catalog could not be fetched
        self._rows_lock = threading.Lock()
        # Background downloads, `docker pull` style: tasks queue up and go ONE BY ONE; the
        # layers of the current task download in parallel, each with its own bar. The worker
        # thread only mutates this state and sets `_dirty`; a timer repaints from the UI thread.
        self._pending: list[TaskRow] = []            # download order; Enter moves a row first
        self._wake = threading.Condition(threading.Lock())
        self._stopping = False
        self._paused = False                         # a task console is open: queued pulls wait
        self._autoload = True                        # start downloading everything on launch
        self._jobs: dict[str, TaskRow] = {}          # queued or downloading, by ref
        self._active: TaskRow | None = None
        self._layers: dict[str, LayerBar] = {}
        self._dl_lock = threading.Lock()
        self._dirty = False
        self._notes: list[str] = []                  # toasts from the worker, shown by the timer
        self._leaf_nodes: dict[str, object] = {}          # ref -> its Tree leaf (relabelled in place)
        self.role = "student"                        # from the pool's /me on mount
        self._show_rejected = True                   # «Отклонённые» shown (z toggles, remembered)

    # -- lifecycle --------------------------------------------------------

    def compose(self) -> ComposeResult:
        """
        Just the Tree (full screen) + Footer with the key legend.

        There is no separate detail pane: everything the student needs -- number,
        ref, credit status, download state -- lives in each row's own label. That
        removes the previous "left says зачтено, right says не начато" desync
        window (the right pane wasn't repainted after a reload) and, per the
        user, "уберём рассинхронизацию".
        """
        tree: Tree[TaskRow | str] = Tree("Каталог", id="tasks")
        tree.show_root = False
        tree.guide_depth = 3
        yield tree
        yield Static("", id="downloads")
        yield Footer()

    # -- theme (Ctrl+P → Theme) is remembered across launches ---------------

    def _theme_file(self):  # noqa: ANN202
        return self.env.root / "tui.json"

    def _prefs(self) -> dict:
        with contextlib.suppress(OSError, ValueError, TypeError):
            data = json.loads(self._theme_file().read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        return {}

    def _save_prefs(self, **changes: object) -> None:
        """Remember UI choices (theme, show_rejected) across launches in tui.json."""
        with contextlib.suppress(OSError):
            self._theme_file().parent.mkdir(parents=True, exist_ok=True)
            self._theme_file().write_text(json.dumps({**self._prefs(), **changes}), encoding="utf-8")

    def _load_theme(self) -> None:
        name = self._prefs().get("theme")
        if name in self.available_themes:
            self.theme = name
        self._show_rejected = bool(self._prefs().get("show_rejected", True))

    def watch_theme(self, theme: str) -> None:
        """Remember the theme the user picked (user, 2026-10-13: «сохрани выбор темы»)."""
        if not getattr(self, "_theme_loaded", False):
            return                                       # the startup default is not a choice
        self._save_prefs(theme=theme)

    def on_mount(self) -> None:
        """Load the catalog once; welcome the student; no ticking timer, no background pulls."""
        self.title = f"hashpass · {self.user}"
        self._load_theme()
        self._theme_loaded = True
        with contextlib.suppress(Exception):               # offline / old pool -> a student's view
            self.role = str(self.client.me(token=self.token).get("role") or "student")
        self.refresh_bindings()
        self._reload_catalog()
        threading.Thread(target=self._download_worker, daemon=True).start()
        self.set_interval(_TICK, self._tick)
        # Textual toast in the corner -- friendly hello, not a modal
        self.notify(f"Добро пожаловать, {self.user}!", severity="information", timeout=4)

    def on_unmount(self) -> None:
        """Stop the download worker on quit (a layer in flight is abandoned with the process)."""
        with self._wake:
            self._stopping = True
            self._wake.notify()

    # -- data -------------------------------------------------------------

    def _reload_catalog(self) -> None:
        """Fetch catalog + progress + local-solved, rebuild `self.rows`, redraw the tree."""
        from hashpass.cli import (  # noqa: PLC0415  (avoid cycle at module load)
            load_solved,
            runnable,
            task_dir,
        )
        try:
            entries = self.client.catalog(token=self.token)
            self._load_error = None
        except Exception as exc:                           # noqa: BLE001 (offline)
            entries = []
            self._load_error = str(exc) or type(exc).__name__
        solved = load_solved(self.env)
        try:
            mine = self.client.progress(token=self.token).get(self.user, {})
        except Exception:                                  # noqa: BLE001
            mine = {}
        rows: list[TaskRow] = []
        for e in entries:
            ref = str(e["ref"])
            if e.get("rejected") and not self._show_rejected:
                continue
            hidden = not runnable(e)
            digest = str(e.get("digest", ""))
            ready = False
            if self.store.exists(ref):
                tdir = task_dir(ref, self.store)
                ready = tdir.exists() and task_digest(tdir) == digest
            server_status = None
            if isinstance(mine.get(ref), dict):
                server_status = str(mine[ref].get("status") or "") or None
            job = self._jobs.get(ref)
            if job is not None:              # downloading right now: keep the live row object
                job.number, job.server, job.local = int(e.get("number") or 0), server_status, ref in solved
                rows.append(job)
                continue
            rows.append(TaskRow(
                ref=ref, number=int(e.get("number") or 0), block=str(e.get("block_name", "")),
                available=bool(e.get("available", True)), digest=digest,
                server=server_status, local=ref in solved,
                state="готово" if ready else "ожидает", hidden=hidden,
                preview=bool(e.get("preview", False)), task_hidden=bool(e.get("hidden", False)),
                block_id=str(e.get("block_id", "")), block_open=bool(e.get("block_open", True)),
                moderation=str(e.get("state") or "approved"),
                pending_update=bool(e.get("pending_update", False)),
                reason=str(e.get("reason") or ""),
                expires_at=float(e["expires_at"]) if e.get("expires_at") else None,
                owner=str(e.get("owner") or "")))
        with self._rows_lock:
            self.rows = rows
        self._paint_tree()
        if self._autoload:
            self._autoqueue()

    def _enqueue(self, row: TaskRow, *, first: bool = False) -> None:
        """Queue a task for background download (one task at a time); `first` jumps the queue."""
        with self._wake:
            if row in self._pending:
                self._pending.remove(row)
            if first:
                self._pending.insert(0, row)
            else:
                self._pending.append(row)
            row.state = "в очереди"
            row.progress = 0.0
            with self._dl_lock:
                self._jobs[row.ref] = row
                self._dirty = True
            self._wake.notify()

    def _autoqueue(self) -> None:
        """Queue every runnable task that is not downloaded yet, in catalog order (docker-pull)."""
        with self._rows_lock:
            todo = [r for r in self.rows
                    if not r.hidden and r.state in ("ожидает", "ошибка") and r.ref not in self._jobs]
        for row in todo:
            self._enqueue(row)

    def _next_job(self) -> TaskRow | None:
        with self._wake:
            while (not self._pending or self._paused) and not self._stopping:
                self._wake.wait()
            return None if self._stopping else self._pending.pop(0)

    @contextlib.contextmanager
    def downloads_paused(self):
        """
        Hold the download queue while a task console is open (the one in flight still finishes).

        The console's typed theory is paced by the same process; background pulls (unpacking,
        sha256) made it stutter (user, 2026-10-15: «подлагивать чтение стало, рывками»).
        """
        with self._wake:
            self._paused = True
        try:
            yield
        finally:
            with self._wake:
                self._paused = False
                self._wake.notify_all()

    def _download_worker(self) -> None:
        """Worker thread: take queued tasks one by one and download each (its layers in parallel)."""
        while (row := self._next_job()) is not None:
            with self._dl_lock:
                self._active, self._layers = row, {}
                row.state = "грузится"
                self._dirty = True
            failed: BaseException | None = None
            try:
                self._download_row(row)
            except Exception as exc:                       # noqa: BLE001
                row.state, failed = "ошибка", exc
            with self._dl_lock:
                self._jobs.pop(row.ref, None)
                self._active = None
                if row.state == "готово":
                    self._notes.append(f"{row.ref}: загружено — Enter, чтобы запустить")
                else:
                    note = failure_note(row.ref, failed or RuntimeError(""))
                    row.error = note.partition(" — ")[2]
                    self._notes.append(note)
                self._dirty = True

    def _on_layer(self, ref: str, done: int, total: int | None) -> None:
        """`pull_many` progress hook (worker threads): update the layer's bar and the row's %."""
        with self._dl_lock:
            bar = self._layers.setdefault(ref, LayerBar(ref))
            bar.done, bar.total = done, total
            bar.state = "ждёт" if total is None and not done else "качается"
            if total is not None and done >= total:
                bar.state = "готово"
            known = [b for b in self._layers.values() if b.total]
            if self._active is not None and known:
                self._active.progress = (sum(min(b.done, b.total or 0) for b in known)
                                         / sum(b.total or 0 for b in known))
            self._dirty = True

    def _download_row(self, row: TaskRow) -> None:
        """
        Pull the row's image closure + the base + its task bundle; set `row.state` at the end.

        The base goes in the same parallel batch, so starting the task afterwards does not
        stall on a big base download in the console.
        """
        from hashpass.cli import base_ref, task_dir  # noqa: PLC0415
        refs = [row.ref]
        with contextlib.suppress(Exception):               # no base on the pool -> task alone
            if self.client.image_digest(base_ref()) is not None:
                refs.append(base_ref())
        self.client.pull_many(refs, self.store, workers=_DOWN_WORKERS, refresh=True,
                              progress=self._on_layer)
        with self._dl_lock:
            for bar in self._layers.values():
                bar.state = "готово"
            self._dirty = True
        if not self.store.exists(row.ref):
            row.state = "ошибка"
            return
        tdir = task_dir(row.ref, self.store)
        if not tdir.exists() or task_digest(tdir) != row.digest:
            self._on_layer(_TASK_LAYER, 0, None)
            self.client.pull_task(row.ref, tdir, token=self.token)
            with self._dl_lock:
                self._layers[_TASK_LAYER].state = "готово"
        row.progress = 1.0
        row.state = "готово"

    def _tick(self) -> None:
        """Timer (UI thread): if the worker changed anything, relabel rows and redraw the panel."""
        with self._dl_lock:
            if not self._dirty:
                return
            self._dirty = False
            notes, self._notes = self._notes, []
            text = self._downloads_text()
        for ref, node in self._leaf_nodes.items():
            row = node.data
            if isinstance(row, TaskRow) and (ref in self._jobs or row.state != "ожидает"):
                node.set_label(row.tree_label())
        panel = self.query_one("#downloads", Static)
        panel.update(text)
        panel.display = bool(text)
        for note in notes:
            self.notify(note, timeout=4)

    def _downloads_text(self) -> str:
        """Render the downloads panel: the current task's layers, `docker pull` style ('' when idle)."""
        row = self._active
        if row is None:
            return ""
        waiting = sum(1 for r in self._jobs.values() if r is not row)
        head = f"[b]Загрузка {escape(row.ref)}[/]"
        if waiting:
            head += f"   [dim]в очереди ещё: {waiting}[/]"
        if not self._layers:
            return head + "\n  [dim]проверяю слои…[/]"
        width = max(len(r) for r in self._layers)
        return "\n".join([head, *(b.line(width) for b in self._layers.values())])

    # -- render -----------------------------------------------------------

    def _paint_tree(self) -> None:
        """Rebuild the Tree from `self.rows`, grouping tasks under their block."""
        tree = self.query_one("#tasks", Tree)
        tree.clear()
        self._leaf_nodes = {}
        with self._rows_lock:
            rows_snapshot = list(self.rows)
        if not rows_snapshot:
            if self._load_error:
                tree.root.add_leaf(f"[red]{escape(self._load_error)}[/]")
            else:
                tree.root.add_leaf("[dim]в пуле пока нет заданий[/]")
            return
        by_block: dict[str, list[TaskRow]] = {}
        order: list[str] = []
        for row in rows_snapshot:
            key = row.block or "Задания"
            if key not in by_block:
                by_block[key] = []
                order.append(key)
            by_block[key].append(row)
        for block in order:
            block_rows = by_block[block]
            visible_open = sum(1 for r in block_rows if r.state == "готово" and not r.hidden)
            head = (f"[b cyan]{block}[/]  "
                    f"[dim]{visible_open}/{len(block_rows)} готово[/]")
            if not block_rows[0].block_open:
                head += "   [yellow]· закрыт для студентов[/]"
            b_node = tree.root.add(head, expand=True, data=block_rows[0].block_id or None)
            for row in block_rows:
                self._leaf_nodes[row.ref] = b_node.add_leaf(row.tree_label(), data=row)
        # focus the tree so arrow keys work immediately
        tree.focus()

    # -- catalog editing (staff) ------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Editing keys exist only for staff: hide/show for an author, moving too for the admin."""
        if action in ("toggle_hidden", "toggle_block"):
            return self.role in ("author", "admin")
        if action == "move":
            return self.role in ("author", "admin")   # an author is told why it is refused
        if action in ("approve", "reject"):
            return self.role == "admin"
        if action in ("delete_task", "toggle_rejected", "view"):
            return self.role in ("author", "admin")
        return super().check_action(action, parameters)

    # -- moderation ---------------------------------------------------------

    def _moderate(self, done: str, call) -> None:
        """Run one moderation call against the pool; flash the outcome; reload."""
        row = self._cursor_row()
        if row is None:
            return
        try:
            call(row)
        except Exception as exc:                           # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=5)
            return
        self._flash(f"{row.ref}: {done}")
        self._after_edit(row.ref)

    def action_approve(self) -> None:
        """Approve the task's current version (a, admin) -- students get it."""
        if self.role == "admin":
            # the digest the admin is looking at: a version re-pushed meanwhile is refused (409)
            self._moderate("одобрено", lambda row: self.client.approve(row.ref, digest=row.digest or None,
                                                                         token=self.token))

    def action_reject(self) -> None:
        """n: reject the task's current version (admin), with an optional reason."""
        row = self._cursor_row()
        if row is None or self.role != "admin":
            return

        def _done(reason: str | None) -> None:
            if reason is not None:
                self._moderate("отклонено", lambda r: self.client.reject(r.ref, reason, token=self.token))

        self.push_screen(ReasonScreen(row.ref), _done)

    def action_delete_task(self) -> None:
        """Delete: remove the task from the pool -- only your own (the admin: any), after a yes."""
        row = self._cursor_row()
        if row is None or self.role not in ("author", "admin"):
            return
        if self.role != "admin" and row.owner != self.user:
            self.notify(f"Это задание автора {row.owner or 'admin'}: удалить его может только он "
                        "или администратор.", severity="warning", timeout=5)
            return

        def _done(yes: bool | None) -> None:  # noqa: FBT001
            if yes:
                self._moderate("удалено с пула", lambda r: self.client.delete_task(r.ref, token=self.token))

        self.push_screen(ConfirmScreen(f"Удалить [b]{escape(row.ref)}[/] с пула насовсем?"), _done)

    def action_view(self) -> None:
        """v: the task's files as its author wrote them (authors and admins)."""
        row = self._cursor_row()
        if row is None or self.role not in ("author", "admin"):
            return
        try:
            files, fetch = listing_or_taskfile(self.client, row.ref, self.token)
        except Exception as exc:                           # noqa: BLE001
            self.notify(f"исходники не открылись: {exc}", severity="error", timeout=5)
            return
        self.push_screen(SourceViewer(row.ref, files, fetch))

    def action_toggle_rejected(self) -> None:
        """z: show or hide the «Отклонённые» block (remembered, shown by default)."""
        self._show_rejected = not self._show_rejected
        self._save_prefs(show_rejected=self._show_rejected)
        self._reload_catalog()
        self._flash("отклонённые показаны" if self._show_rejected else "отклонённые скрыты")

    def _cursor_row(self) -> TaskRow | None:
        node = self.query_one("#tasks", Tree).cursor_node
        return node.data if node is not None and isinstance(node.data, TaskRow) else None

    def _after_edit(self, ref: str) -> None:
        """Reload the catalog from the pool and put the cursor back on the edited task."""
        self._reload_catalog()
        node = self._leaf_nodes.get(ref)
        if node is not None:      # the rebuilt tree has no line numbers until it is laid out
            tree = self.query_one("#tasks", Tree)
            self.call_after_refresh(tree.move_cursor, node)

    def action_vim(self, where: str) -> None:
        """Walk the tree with vim keys (j/k/h/l/g/G)."""
        vim_walk(self.query_one("#tasks", Tree), where)

    def action_toggle_hidden(self) -> None:
        """x: hide a task from students or show it again (an author -- only its own)."""
        row = self._cursor_row()
        if row is None or self.role not in ("author", "admin"):
            return
        hide = not row.task_hidden
        try:
            self.client.set_task_hidden(row.ref, hidden=hide, token=self.token)
        except Exception as exc:                           # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=5)
            return
        self._after_edit(row.ref)
        self._flash(f"{row.ref}: {'скрыто от студентов' if hide else 'показано студентам'}")

    def action_toggle_block(self) -> None:
        """o: open or close for students the block under the cursor (or the cursor task's block)."""
        if self.role not in ("author", "admin"):
            return
        node = self.query_one("#tasks", Tree).cursor_node
        row = node.data if node is not None and isinstance(node.data, TaskRow) else None
        block_id = row.block_id if row is not None else (node.data if node is not None else None)
        if not block_id:
            return
        current = next((r for r in self.rows if r.block_id == block_id), None)
        if current is None:
            return
        if block_id == "rejected":
            self.notify("«Отклонённые» — служебный блок: студентам он не показывается.",
                        severity="warning", timeout=5)
            return
        open_ = not current.block_open
        try:
            self.client.set_block_open(str(block_id), open_=open_, token=self.token)
        except Exception as exc:                           # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=5)
            return
        self._after_edit(current.ref)
        self._flash(f"блок «{current.block}»: {'открыт' if open_ else 'закрыт'} для студентов")

    def action_move(self, step: int) -> None:
        """Shift+↑/↓: move a task one place; at a block's edge it crosses into the next block."""
        row = self._cursor_row()
        if row is None or self.role not in ("author", "admin"):
            return
        if self.role != "admin":
            self.notify("Порядок заданий меняет только администратор", severity="warning",
                        timeout=4)
            return
        try:
            moved = self.client.move_task(row.ref, step, token=self.token)
        except Exception as exc:                           # noqa: BLE001
            self.notify(str(exc), severity="error", timeout=5)
            return
        if moved:
            self._after_edit(row.ref)

    def _flash(self, msg: str) -> None:
        """One-shot toast in the corner (no detail pane to overwrite any more)."""
        if msg:
            self.notify(msg, timeout=3)

    # -- events -----------------------------------------------------------

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter on a task -> download-if-needed + run. Enter on a block -> collapse/expand it."""
        row = event.node.data if isinstance(event.node.data, TaskRow) else None
        if row is None:
            # block header: toggle expand/collapse explicitly so Enter feels intuitive
            # (Tree.NodeSelected fires but Textual doesn't toggle on its own here)
            event.node.toggle()
            return
        if row.hidden:
            self._flash("Задание закрыто преподавателем")
            return
        if row.state == "грузится":
            self._flash(f"{row.ref} загружается — Enter, когда будет готово")
            return
        if row.state == "в очереди":
            self._enqueue(row, first=True)
            self._flash(f"{row.ref} — следующим в загрузке")
            return
        if row.state != "готово":   # ожидает / ошибка -> download in the background, UI stays live
            self._enqueue(row, first=True)
            self._flash(f"Загружаю {row.ref} в фоне — можно выбирать другие задания")
            return
        from hashpass.cli import Io, _now_iso, cmd_pool_run  # noqa: PLC0415
        # The run happens inside suspend(), where the real terminal is visible: messages go to
        # sys.stdout so the student sees «пул недоступен …» / «собираю локально» before a long
        # local base build (a silent Io hid them). `write` looks sys.stdout up per call --
        # Textual swaps sys.stdout while the app runs, so it must not be bound up front.
        # `read` is the real terminal: after the task the verdict screen asks «следующее
        # задание / в меню». `clock` must be a zero-arg callable returning an ISO stamp --
        # reuse cli._now_iso (time.strftime needs a format string).
        io = Io(read=_read_line, write=lambda s: sys.stdout.write(s),  # noqa: PLW0108
                clock=_now_iso)
        with self.suspend(), self.downloads_paused():
            self._task_frame_start(row)
            cmd_pool_run(self.env, row.ref, io)
        # Textual's alt-screen buffer resumes on __exit__ — TUI is instantly back
        self._reload_catalog()

    @staticmethod
    def _task_frame_start(row: TaskRow) -> None:
        """Clear the screen and print a thin ANSI banner before the task's own console starts."""
        title = f"{row.ref}  ·  блок «{row.block or 'Задания'}»"
        bar = "─" * min(len(title) + 4, 78)
        sys.stdout.write("\x1b[2J\x1b[H")                      # clear + home
        sys.stdout.write(f"\x1b[1;36m╭{bar}╮\x1b[0m\n")
        sys.stdout.write(f"\x1b[1;36m│\x1b[0m  \x1b[1m{title}\x1b[0m"
                         + " " * max(0, len(bar) - len(title) - 2)
                         + "\x1b[1;36m│\x1b[0m\n")
        sys.stdout.write(f"\x1b[1;36m╰{bar}╯\x1b[0m\n\n")
        sys.stdout.flush()

    def action_refresh(self) -> None:
        """r: reload the catalog; tasks not downloaded yet join the background queue."""
        self._reload_catalog()

    def action_resync(self) -> None:
        """s: re-submit tasks solved locally but not credited on the server."""
        from hashpass.cli import Io, _now_iso, _resync  # noqa: PLC0415
        buf: list[str] = []
        _resync(self.env, self.url, self.user, self.token,
                Io(read=lambda _p: None, write=buf.append, clock=_now_iso))
        self._flash("\n".join(buf).strip() or "готово")
        self._reload_catalog()


def failure_note(ref: str, exc: BaseException) -> str:
    """Word the toast for a failed download: what failed and what to do, not a bare «не удалось»."""
    text = str(exc)
    if "password is required" in text or ("sudo" in text and "terminal is required" in text):
        why = "нужен пароль sudo — перезапусти hashpass и введи его"
    elif "подключиться к пулу" in text or "timed out" in text:
        why = "пул недоступен — проверь сеть и нажми r"
    else:
        why = text.splitlines()[0][:120] if text else type(exc).__name__
    return f"{ref}: не удалось загрузить — {why}"


def run_tui(env: Home, url: str, user: str, token: str) -> int:
    """Enter the Textual app; on quit print a friendly goodbye. Errors bubble up."""
    PoolTUI(env, url, user, token).run()
    sys.stdout.write(f"\n\x1b[36mДо скорой встречи, {user}!\x1b[0m\n")
    sys.stdout.flush()
    return 0
