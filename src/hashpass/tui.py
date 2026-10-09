"""
Full-screen Textual TUI for the student pool client (the `hashpass` menu).

Left: a `Tree` of blocks -> tasks -- arrows navigate, Enter on a leaf runs it,
Enter on a block collapses/expands it (native Tree behaviour, nothing to relearn).
Right: a splash card on empty selection, a rich task-detail card on a highlighted
task. Statuses are words (решено / зачтено / не начато / грузится). Hidden tasks
render as "№N · закрыто" without the ref -- the student sees the slot but not
which task it is; an author/admin (`preview` from the pool) sees the ref with a
«скрыто» badge and can run it. Bindings honour both English AND Russian keyboard layouts, so
q/й, r/к, s/ы all work regardless of the OS layout.

If the runtime `textual` package isn't installed, `cli.cmd_pool_home` falls back
to the plain text menu; `run_tui` never raises for that path -- the ImportError
happens on this module's own import, before any function is called.
"""
from __future__ import annotations

import contextlib
import queue
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, Tree

from hashpass.imagestore.store import ImageStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest

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
            return f"[dim]№{self.number} · закрыто[/]"
        local_dot = "[green]●[/] решено" if self.local else "[dim]○ не решено[/]"
        server_dot = "[green]●[/] зачтено" if self.server == "passed" else "[dim]○ не зачтено[/]"
        if self.state == "готово":
            down = "[green]●[/] загружено"
        elif self.state == "грузится":
            down = f"[cyan]{_bar(self.progress, 10)} {self.progress * 100:3.0f}%[/]"
        elif self.state == "в очереди":
            down = "[cyan]◌ в очереди[/]"
        elif self.state == "ошибка":
            down = "[red]✗ ошибка загрузки[/]"
        else:
            down = "[dim]○ не загружено[/]"
        tail = f"   {local_dot}   {server_dot}   {down}"
        if self.preview:
            tail += "   [yellow]· скрыто[/]"
        return f"№{self.number} · {self.ref}{tail}"


class PoolTUI(App):
    """Full-screen blocks/tasks tree + a rich detail card + one-Enter run."""

    CSS = """
    Screen { background: $surface; }
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
    ]

    def __init__(self, env: Home, url: str, user: str, token: str) -> None:
        """Wire creds + env; the rows list stays empty until on_mount reloads."""
        super().__init__()
        self.env = env
        self.url = url
        self.user = user
        self.token = token
        self.client = RemoteRegistry(url)
        self.store = ImageStore(env.images)
        self.rows: list[TaskRow] = []
        self._load_error: str | None = None    # why the catalog could not be fetched
        self._rows_lock = threading.Lock()
        # Background downloads, `docker pull` style: tasks queue up and go ONE BY ONE; the
        # layers of the current task download in parallel, each with its own bar. The worker
        # thread only mutates this state and sets `_dirty`; a timer repaints from the UI thread.
        self._queue: queue.Queue[TaskRow | None] = queue.Queue()
        self._jobs: dict[str, TaskRow] = {}          # queued or downloading, by ref
        self._active: TaskRow | None = None
        self._layers: dict[str, LayerBar] = {}
        self._dl_lock = threading.Lock()
        self._dirty = False
        self._notes: list[str] = []                  # toasts from the worker, shown by the timer
        self._leaf_nodes: dict[str, object] = {}          # ref -> its Tree leaf (relabelled in place)

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

    def on_mount(self) -> None:
        """Load the catalog once; welcome the student; no ticking timer, no background pulls."""
        self.title = f"hashpass · {self.user}"
        self._reload_catalog()
        threading.Thread(target=self._download_worker, daemon=True).start()
        self.set_interval(_TICK, self._tick)
        # Textual toast in the corner -- friendly hello, not a modal
        self.notify(f"Добро пожаловать, {self.user}!", severity="information", timeout=4)

    def on_unmount(self) -> None:
        """Stop the download worker on quit (a layer in flight is abandoned with the process)."""
        self._queue.put(None)

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
                preview=bool(e.get("preview", False))))
        with self._rows_lock:
            self.rows = rows
        self._paint_tree()

    def _enqueue(self, row: TaskRow) -> None:
        """Queue a task for background download (tasks are fetched one at a time, in order)."""
        row.state = "в очереди"
        row.progress = 0.0
        with self._dl_lock:
            self._jobs[row.ref] = row
            self._dirty = True
        self._queue.put(row)

    def _download_worker(self) -> None:
        """Worker thread: take queued tasks one by one and download each (its layers in parallel)."""
        while (row := self._queue.get()) is not None:
            with self._dl_lock:
                self._active, self._layers = row, {}
                row.state = "грузится"
                self._dirty = True
            try:
                self._download_row(row)
            except Exception:                              # noqa: BLE001
                row.state = "ошибка"
            with self._dl_lock:
                self._jobs.pop(row.ref, None)
                self._active = None
                self._notes.append(f"№{row.number} {row.ref}: загружено — Enter, чтобы запустить"
                                   if row.state == "готово" else
                                   f"№{row.number} {row.ref}: не удалось загрузить")
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
        head = f"[b]Загрузка №{row.number} {escape(row.ref)}[/]"
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
            b_node = tree.root.add(head, expand=True)
            for row in block_rows:
                self._leaf_nodes[row.ref] = b_node.add_leaf(row.tree_label(), data=row)
        # focus the tree so arrow keys work immediately
        tree.focus()

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
        if row.state in ("в очереди", "грузится"):
            self._flash(f"{row.ref} уже загружается — запустится по Enter, когда будет готово")
            return
        if row.state != "готово":   # ожидает / ошибка -> download in the background, UI stays live
            self._enqueue(row)
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
        with self.suspend():
            self._task_frame_start(row)
            cmd_pool_run(self.env, row.ref, io)
        # Textual's alt-screen buffer resumes on __exit__ — TUI is instantly back
        self._reload_catalog()

    @staticmethod
    def _task_frame_start(row: TaskRow) -> None:
        """Clear the screen and print a thin ANSI banner before the task's own console starts."""
        title = f"№{row.number}  ·  {row.ref}  ·  блок «{row.block or 'Задания'}»"
        bar = "─" * min(len(title) + 4, 78)
        sys.stdout.write("\x1b[2J\x1b[H")                      # clear + home
        sys.stdout.write(f"\x1b[1;36m╭{bar}╮\x1b[0m\n")
        sys.stdout.write(f"\x1b[1;36m│\x1b[0m  \x1b[1m{title}\x1b[0m"
                         + " " * max(0, len(bar) - len(title) - 2)
                         + "\x1b[1;36m│\x1b[0m\n")
        sys.stdout.write(f"\x1b[1;36m╰{bar}╯\x1b[0m\n\n")
        sys.stdout.flush()

    def action_refresh(self) -> None:
        """r: reload the catalog. Nothing downloads here -- Enter on a row does that."""
        self._reload_catalog()

    def action_resync(self) -> None:
        """s: re-submit tasks solved locally but not credited on the server."""
        from hashpass.cli import Io, _now_iso, _resync  # noqa: PLC0415
        buf: list[str] = []
        _resync(self.env, self.url, self.user, self.token,
                Io(read=lambda _p: None, write=buf.append, clock=_now_iso))
        self._flash("\n".join(buf).strip() or "готово")
        self._reload_catalog()


def run_tui(env: Home, url: str, user: str, token: str) -> int:
    """Enter the Textual app; on quit print a friendly goodbye. Errors bubble up."""
    PoolTUI(env, url, user, token).run()
    sys.stdout.write(f"\n\x1b[36mДо скорой встречи, {user}!\x1b[0m\n")
    sys.stdout.flush()
    return 0
