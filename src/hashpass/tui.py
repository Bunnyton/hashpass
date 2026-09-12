"""
Full-screen Textual TUI for the student pool client (the `hashpass` menu).

Left: a `Tree` of blocks -> tasks -- arrows navigate, Enter on a leaf runs it,
Enter on a block collapses/expands it (native Tree behaviour, nothing to relearn).
Right: a splash card on empty selection, a rich task-detail card on a highlighted
task. Statuses are words (решено / зачтено / не начато / грузится). Hidden tasks
render as "№N · закрыто" without the ref -- the student sees the slot but not
which task it is. Bindings honour both English AND Russian keyboard layouts, so
q/й, r/к, s/ы all work regardless of the OS layout.

If the runtime `textual` package isn't installed, `cli.cmd_pool_home` falls back
to the plain text menu; `run_tui` never raises for that path -- the ImportError
happens on this module's own import, before any function is called.
"""
from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Tree

from hashpass.imagestore.store import ImageStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest

if TYPE_CHECKING:
    from hashpass.cli import Home

_DOWN_WORKERS = 6            # parallel background downloads


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

    def status_label(self) -> str:
        """One-line status without Rich markup (used by tests / plain-text callers)."""
        if self.hidden:
            return "закрыто"
        parts = []
        parts.append("решено" if self.local else "не решено")
        parts.append("зачтено" if self.server == "passed" else "не зачтено")
        head = " · ".join(parts)
        if self.state == "готово":
            return head
        return f"{head} · {self.state}"

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
        tail = f"   {local_dot}   {server_dot}"
        if self.state == "грузится":
            tail += "   [cyan]· грузится[/]"
        elif self.state == "ошибка":
            tail += "   [red]· ошибка[/]"
        return f"№{self.number} · {self.ref}{tail}"


class PoolTUI(App):
    """Full-screen blocks/tasks tree + a rich detail card + one-Enter run."""

    CSS = """
    Screen { background: $surface; }
    Tree { padding: 1 2; background: $surface; }
    Tree > .tree--cursor { background: $accent 40%; color: $text; }
    Tree > .tree--highlight-line { background: $accent 20%; }
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
        self._rows_lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = None

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
        yield Footer()

    def on_mount(self) -> None:
        """Load the catalog once; welcome the student; no ticking timer, no background pulls."""
        self.title = f"hashpass · {self.user}"
        self._reload_catalog()
        self._pool = ThreadPoolExecutor(max_workers=_DOWN_WORKERS)
        # Textual toast in the corner -- friendly hello, not a modal
        self.notify(f"Добро пожаловать, {self.user}!", severity="information", timeout=4)

    def on_unmount(self) -> None:
        """Stop the on-demand download pool on quit."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    # -- data -------------------------------------------------------------

    def _reload_catalog(self) -> None:
        """Fetch catalog + progress + local-solved, rebuild `self.rows`, redraw the tree."""
        from hashpass.cli import (  # noqa: PLC0415  (avoid cycle at module load)
            load_solved,
            task_dir,
        )
        try:
            entries = self.client.catalog(token=self.token)
        except Exception:                                  # noqa: BLE001 (offline)
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
        self._paint_tree()

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

    def _paint_tree(self) -> None:
        """Rebuild the Tree from `self.rows`, grouping tasks under their block."""
        tree = self.query_one("#tasks", Tree)
        tree.clear()
        with self._rows_lock:
            rows_snapshot = list(self.rows)
        if not rows_snapshot:
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
                b_node.add_leaf(row.tree_label(), data=row)
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
        if row.state != "готово":
            self._flash(f"Загружаю {row.ref}…")
            self.refresh()
            self._download_row(row)
            self._paint_tree()   # let the row label reflect the new state
            if row.state != "готово":
                self._flash(f"Не удалось загрузить {row.ref}: {row.state}")
                return
        from hashpass.cli import Io, cmd_pool_run  # noqa: PLC0415
        # Silent io: don't let cmd_pool_run's post-run status messages ("решено",
        # "зачтено") flash on the terminal between the task's exit and Textual's
        # alt-screen resume -- the same info is already in the tree after reload.
        silent = Io(read=lambda _p: None, write=lambda _s: None, clock=time.strftime)
        with self.suspend():
            self._task_frame_start(row)
            cmd_pool_run(self.env, row.ref, silent)
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
        from hashpass.cli import Io, _resync  # noqa: PLC0415
        buf: list[str] = []
        _resync(self.env, self.url, self.user, self.token,
                Io(read=lambda _p: None, write=buf.append, clock=time.strftime))
        self._flash("[green]" + ("\n".join(buf).strip() or "готово") + "[/]")
        self._reload_catalog()


def run_tui(env: Home, url: str, user: str, token: str) -> int:
    """Enter the Textual app; on quit print a friendly goodbye. Errors bubble up."""
    PoolTUI(env, url, user, token).run()
    sys.stdout.write(f"\n\x1b[36mДо скорой встречи, {user}!\x1b[0m\n")
    sys.stdout.flush()
    return 0
