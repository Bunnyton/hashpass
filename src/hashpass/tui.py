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

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Static, Tree

from hashpass.imagestore.store import ImageStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest

if TYPE_CHECKING:
    from hashpass.cli import Home

_DOWN_WORKERS = 6            # parallel background downloads

_SPLASH = """\
[b cyan]hashpass[/]  ·  ваша живая консоль Debian

[dim]Слева — блоки с заданиями. Выберите одно стрелками
и нажмите [b]Enter[/b] — оно запустится в настоящей консоли.[/]

  ▸ [b]Enter[/]   запустить задание
  ▸ [b]↑ ↓[/]     навигация
  ▸ [b]←  →[/]    свернуть / развернуть блок
  ▸ [b]r[/]       обновить каталог с пула
  ▸ [b]s[/]       самопроверка (переотправить решённое)
  ▸ [b]q[/]       выход

[dim]Работают обе раскладки клавиатуры (q/й, r/к, s/ы).[/]
"""


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

    def tree_label(self) -> str:
        """Render the one-line label as it appears in the tree (Rich markup)."""
        if self.hidden:
            return f"[dim]№{self.number} · закрыто[/]"
        badge = ""
        if self.server == "passed":
            badge = "[green]● зачтено[/]"
        elif self.local:
            badge = "[yellow]● решено[/]"
        else:
            badge = "[dim]○ не начато[/]"
        state = ""
        if self.state == "грузится":
            state = "  [cyan]грузится…[/]"
        elif self.state == "ошибка":
            state = "  [red]ошибка[/]"
        elif self.state == "ожидает" and self.server != "passed" and not self.local:
            state = ""
        return f"№{self.number} · {self.ref}   {badge}{state}"


class PoolTUI(App):
    """Full-screen blocks/tasks tree + a rich detail card + one-Enter run."""

    CSS = """
    Screen { layout: horizontal; }
    #tasks { width: 46%; border-right: heavy $accent-lighten-2; background: $surface; }
    #detail { padding: 2 3; background: $panel; }
    Tree { padding: 1 1 1 1; background: $surface; }
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
        """Header + horizontal split (Tree | detail Static) + footer with keybinds."""
        tree: Tree[TaskRow | str] = Tree("Каталог", id="tasks")
        tree.show_root = False
        tree.guide_depth = 3
        with Horizontal():
            yield tree
            yield Static(_SPLASH, id="detail", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        """Load the catalog once; no ticking timer, no background pulls until Enter."""
        self.title = f"hashpass · {self.user}"
        self._reload_catalog()
        self._pool = ThreadPoolExecutor(max_workers=_DOWN_WORKERS)

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

    def _update_detail(self, row: TaskRow | None) -> None:
        """Rich card on the right for the currently-highlighted task (splash if none)."""
        detail = self.query_one("#detail", Static)
        if row is None:
            detail.update(_SPLASH)
            return
        if row.hidden:
            detail.update(
                f"[b]№{row.number}[/]   [dim]{row.block or 'Задания'}[/]\n\n"
                "[b red]🔒 закрыто[/]\n\n"
                "[dim]Преподаватель пока не открыл это задание.[/]")
            return
        # Big status pill
        if row.server == "passed":
            pill = "[b green on black] ● зачтено [/]"
        elif row.local:
            pill = "[b yellow on black] ● решено на этой машине [/]"
        else:
            pill = "[b white on grey30] ○ не начато [/]"
        # Download state
        if row.state == "готово":
            load = "[green]готово, можно запускать[/]"
        elif row.state == "грузится":
            load = "[cyan]грузится…[/]"
        elif row.state == "ошибка":
            load = "[red]ошибка загрузки[/]"
        else:
            load = "[dim]ещё не загружено — Enter скачает и запустит[/]"
        detail.update(
            f"[b]№{row.number}[/]   [dim]блок «{row.block or 'Задания'}»[/]\n"
            f"[b cyan]{row.ref}[/]\n\n"
            f"{pill}\n\n"
            f"Локально: {load}\n\n"
            "[dim]────────────────────────────────[/]\n"
            "[b]Enter[/] — запустить задание\n"
            "[dim]r — обновить · s — самопроверка · q — выход[/]")

    def _flash(self, msg: str) -> None:
        """Overwrite the detail pane with a one-shot status (auto-clears on next highlight)."""
        self.query_one("#detail", Static).update(msg or _SPLASH)

    # -- events -----------------------------------------------------------

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Show the task detail on the right whenever the highlight moves."""
        row = event.node.data if isinstance(event.node.data, TaskRow) else None
        self._update_detail(row)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter on a task -> download-if-needed + run. Enter on a block -> Tree toggles it."""
        row = event.node.data if isinstance(event.node.data, TaskRow) else None
        if row is None:
            return                                 # let Tree's own expand/collapse fire
        if row.hidden:
            self._flash("[yellow]Это задание закрыто преподавателем.[/]")
            return
        if row.state != "готово":
            self._flash(f"[cyan]Загружаю {row.ref}…[/]  [dim](без сети — займёт несколько секунд)[/]")
            self.refresh()
            self._download_row(row)
            if row.state != "готово":
                self._flash(f"[red]Не удалось загрузить {row.ref}: {row.state}[/]")
                return
        from hashpass.cli import cmd_pool_run  # noqa: PLC0415
        with self.suspend():
            cmd_pool_run(self.env, row.ref)
        self._reload_catalog()

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
    """Enter the Textual app; on quit, return 0. Errors bubble up so cmd_pool_home can fall back."""
    PoolTUI(env, url, user, token).run()
    return 0
