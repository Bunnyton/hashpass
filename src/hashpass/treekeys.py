"""
vim keys for the hashpass trees (catalog, source viewer).

User, 2026-10-15: «в hashpass интерфейс заданий добавь поддержку клавиш как в vim hjkl как
минимум». j/k -- down/up, h -- fold / up to the parent, l -- unfold / into it / open (as Enter),
g/G -- top/bottom. Textual binds characters, so the Russian layout gets the same physical keys.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding

if TYPE_CHECKING:
    from textual.widgets import Tree

VIM_BINDINGS = [
    Binding("j,о", "vim('down')", "Вниз", show=False),
    Binding("k,л", "vim('up')", "Вверх", show=False),
    Binding("h,р", "vim('left')", "Назад", show=False),
    Binding("l,д", "vim('right')", "Открыть", show=False),
    Binding("g,п", "vim('top')", "В начало", show=False),
    Binding("G,П", "vim('bottom')", "В конец", show=False),
]


def _left(tree: Tree, node) -> None:
    if node.allow_expand and node.is_expanded and node is not tree.root:
        node.collapse()
    elif node.parent is not None and (node.parent is not tree.root or tree.show_root):
        tree.move_cursor(node.parent)


def _right(tree: Tree, node) -> None:
    if not node.allow_expand:
        tree.action_select_cursor()                   # a leaf: open it, as Enter
    elif not node.is_expanded:
        node.expand()
    elif node.children:
        tree.move_cursor(node.children[0])


def vim_walk(tree: Tree, where: str) -> None:
    """Move over `tree` the vim way: down/up/left/right/top/bottom."""
    moves = {"down": tree.action_cursor_down, "up": tree.action_cursor_up}
    if where in moves:
        moves[where]()
    elif where == "top":
        tree.cursor_line = 0
    elif where == "bottom":
        tree.cursor_line = tree.last_line
    elif tree.cursor_node is not None:
        (_left if where == "left" else _right)(tree, tree.cursor_node)
