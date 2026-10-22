"""
Choosing a course inside the hashpass TUI (spec 2026-10-21 §9).

One field and one list: typing filters the pool's courses (and the student's own); a pasted
course link is taken as is. Enter picks the highlighted course. The screen only answers WHICH
course -- joining, requesting access and switching are the app's job.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual import work
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult

COURSE_CSS = """
CoursePicker { align: center middle; }
#course-card { width: 84; height: auto; max-height: 90%; padding: 1 2; border: thick $accent;
               background: $panel; }
#course-card OptionList { height: auto; max-height: 20; margin-top: 1; }
#course-note { color: $text-muted; height: auto; margin-top: 1; }
"""

LINK_PREFIX = "link:"


class CoursePicker(ModalScreen[str | None]):
    """Pick a course: returns `owner/name`, `link:<url>` for a pasted link, or None (Esc)."""

    CSS = COURSE_CSS
    BINDINGS = [Binding("escape", "cancel", "Отмена")]   # noqa: RUF012

    def __init__(self, client: object, token: str, mine: list[str], current: str | None) -> None:
        """Keep the pool client (its `courses()` lists what the student may see) and the own list."""
        super().__init__()
        self.client = client
        self.token = token
        self.mine = mine
        self.current = current
        self.rows: list[dict] = []

    def compose(self) -> ComposeResult:
        """Build the field, the list and a one-line hint."""
        with Vertical(id="course-card"):
            yield Label("[b]Курсы[/] — выберите курс или вставьте ссылку со страницы курса")
            yield Input(placeholder="поиск по названию… или https://<пул>/c/<владелец>/<курс>", id="course-q")
            yield OptionList(id="course-list")
            yield Label("Enter — выбрать · Esc — назад", id="course-note")

    def on_mount(self) -> None:
        """Load the list in the background (a slow pool never freezes the screen)."""
        self._load("")

    @work(thread=True, exclusive=True)
    def _load(self, q: str) -> None:
        try:
            rows = self.client.courses(q, token=self.token) or []
        except Exception as exc:                          # noqa: BLE001  (offline: own list only)
            rows = []
            self.app.call_from_thread(self._note, f"пул недоступен: {exc}")
        seen = {r["ref"] for r in rows}
        rows += [{"ref": ref, "title": ref, "role": None, "visibility": "?"} for ref in self.mine
                 if ref not in seen and (not q or q.casefold() in ref.casefold())]
        self.app.call_from_thread(self._show, rows)

    def _note(self, text: str) -> None:
        self.query_one("#course-note", Label).update(escape(text))

    def _show(self, rows: list[dict]) -> None:
        mine = set(self.mine)
        rows.sort(key=lambda r: (r["ref"] not in mine and not r.get("role"), r["ref"]))
        self.rows = rows
        options = self.query_one("#course-list", OptionList)
        options.clear_options()
        for r in rows:
            mark = "▸ " if r["ref"] == self.current else ("★ " if r["ref"] in mine or r.get("role") else "  ")
            lock = " [dim](приватный)[/]" if r.get("visibility") == "private" else ""
            title = escape(str(r.get("title") or r["ref"]))
            options.add_option(Option(f"{mark}[b]{title}[/]  [dim]{escape(r['ref'])}[/]{lock}", id=r["ref"]))
        if not rows:
            options.add_option(Option("[dim]курсов нет — вставьте ссылку на курс[/]", id="", disabled=True))
        else:
            options.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter as the student types (a link is not searched)."""
        if "/c/" not in event.value:
            self._load(event.value.strip())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the field: a link -> take it; else the highlighted course."""
        text = event.value.strip()
        if "/c/" in text:
            self.dismiss(LINK_PREFIX + text)
            return
        options = self.query_one("#course-list", OptionList)
        if options.highlighted is not None and self.rows:
            self.dismiss(self.rows[options.highlighted]["ref"])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter / click on a course."""
        if event.option.id:
            self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        """Esc: keep the current course."""
        self.dismiss(None)


class AskScreen(ModalScreen[str | None]):
    """One line of text (Enter -- send it, Esc -- cancel): an access request's comment."""

    BINDINGS = [Binding("escape", "cancel", "Отмена")]   # noqa: RUF012

    def __init__(self, question: str, placeholder: str = "") -> None:
        """Remember the question and a hint for the field."""
        super().__init__()
        self.question = question
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        """Build the question and the field."""
        with Vertical(id="dialog"):
            yield Label(self.question)
            yield Input(placeholder=self.placeholder, id="ask")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter: answer with what was typed."""
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        """Esc: no answer."""
        self.dismiss(None)
