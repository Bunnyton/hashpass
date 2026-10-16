"""
Login and sign-up inside the hashpass TUI (spec 2026-10-16).

User, 2026-10-16: «форму логина более красивую и удобную уже внутри системы и кнопку
зарегистрироваться, разделим login и registration». Two screens, one card each: a wrong password
says so in the form (it no longer turns into a sign-up), «Зарегистрироваться» is its own screen.
The pool calls run in a thread so a slow pool never freezes the form.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual import work
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static

from hashpass import account
from hashpass.registry.passwords import BadLoginError, validate_login

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from hashpass.cli import Home

# (url, user, token) of a signed-in session
Session = tuple[str, str, str]

AUTH_CSS = """
LoginScreen, RegisterScreen { align: center middle; background: $surface; }
#auth-card { width: 64; height: auto; padding: 1 3; border: round $accent;
             background: $panel; }
#auth-title { width: 100%; content-align: center middle; text-style: bold; color: $accent; }
#auth-sub { width: 100%; content-align: center middle; color: $text-muted; margin-bottom: 1; }
#auth-card Label { margin-top: 1; color: $text-muted; }
#auth-card Input { margin: 0; }
#auth-error { color: $error; height: auto; margin-top: 1; }
#auth-note { color: $text-muted; height: auto; margin-top: 1; }
#login-hint { color: $warning; height: auto; }
#auth-buttons { height: auto; margin-top: 1; align-horizontal: center; }
#auth-buttons Button { margin: 0 1; }
"""

PASSWORD_RULE = "Пароль: от 8 символов, хотя бы одна буква, одна цифра и один спецсимвол."  # noqa: S105  (a hint, not a password)
TEACHER_SEES = "Команды и их вывод в заданиях видны преподавателю."


class LoginScreen(Screen[Session | None]):
    """Pool address, login, password; «Войти» and «Зарегистрироваться»."""

    CSS = AUTH_CSS
    BINDINGS = [Binding("escape", "app.quit", "Выход")]   # noqa: RUF012

    def __init__(self, env: Home, url: str = "", *, user: str = "", error: str = "") -> None:
        """Prefill the pool (and login); `error` is shown at once (e.g. the account is gone)."""
        super().__init__()
        self.env = env
        self.url = url
        self.user = user
        self.error = error

    def compose(self) -> ComposeResult:
        """Build the card."""
        with Center(), Vertical(id="auth-card"):
            yield Static("hashpass", id="auth-title")
            yield Static("Вход", id="auth-sub")
            yield Label("Адрес пула")
            yield Input(self.url, placeholder="например 1.2.3.4:8080", id="pool")
            yield Label("Логин")
            yield Input(self.user, placeholder="ваш логин", id="user")
            yield Label("Пароль")
            yield Input(placeholder="пароль", password=True, id="password")
            yield Static(self.error, id="auth-error")
            with Horizontal(id="auth-buttons"):
                yield Button("Войти", variant="primary", id="login")
                yield Button("Зарегистрироваться", id="to-register")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the first empty field."""
        for wid in ("pool", "user", "password"):
            field = self.query_one(f"#{wid}", Input)
            if not field.value:
                field.focus()
                return

    def _say(self, text: str) -> None:
        self.query_one("#auth-error", Static).update(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter: to the next field, or -- in the password -- log in."""
        if event.input.id == "password":
            self.submit()
        else:
            self.focus_next()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Войти / Зарегистрироваться."""
        if event.button.id == "login":
            self.submit()
        elif event.button.id == "to-register":
            self.app.push_screen(
                RegisterScreen(self.env, self.query_one("#pool", Input).value.strip(),
                               user=self.query_one("#user", Input).value.strip()),
                callback=self._registered)

    def _registered(self, session: Session | None) -> None:
        if session is not None:   # once the sign-up screen is really gone, close this one too
            def close() -> None:  # not awaited: a screen may not await its own dismiss
                self.dismiss(session)
            self.call_after_refresh(close)

    def submit(self) -> None:
        """Log in with what is typed (in a thread)."""
        self._say("Вхожу…")
        self._login(self.query_one("#pool", Input).value.strip(),
                    self.query_one("#user", Input).value.strip(),
                    self.query_one("#password", Input).value)

    @work(thread=True, exclusive=True)
    def _login(self, url: str, user: str, password: str) -> None:
        try:
            token = account.login(self.env, url, user, password)
        except account.AuthError as exc:
            self.app.call_from_thread(self._failed, str(exc))
            return
        self.app.call_from_thread(self.dismiss, (url, user, token))

    def _failed(self, text: str) -> None:
        self._say(text)
        field = self.query_one("#password", Input)
        field.value = ""
        field.focus()


class RegisterScreen(Screen[Session | None]):
    """A new student account: login, password twice, group, comment."""

    CSS = AUTH_CSS
    BINDINGS = [Binding("escape", "back", "Назад ко входу")]   # noqa: RUF012

    def __init__(self, env: Home, url: str = "", *, user: str = "") -> None:
        """Carry the pool (and a login already typed) over from the login form."""
        super().__init__()
        self.env = env
        self.url = url
        self.user = user

    def compose(self) -> ComposeResult:
        """Build the card."""
        with Center(), Vertical(id="auth-card"):
            yield Static("hashpass", id="auth-title")
            yield Static("Регистрация", id="auth-sub")
            yield Label("Адрес пула")
            yield Input(self.url, placeholder="например 1.2.3.4:8080", id="pool")
            yield Label("Логин")
            yield Input(self.user, placeholder="латиница, цифры, . _ -", id="user")
            yield Static("", id="login-hint")
            yield Label("Пароль")
            yield Input(placeholder="пароль", password=True, id="password")
            yield Label("Повторите пароль")
            yield Input(placeholder="ещё раз", password=True, id="password2")
            yield Label("Группа (необязательно)")
            yield Input(placeholder="например ИУ7-31", id="group")
            yield Label("Комментарий (необязательно)")
            yield Input(placeholder="имя и фамилия", id="comment")
            yield Static(f"{PASSWORD_RULE}\n{TEACHER_SEES}", id="auth-note")
            yield Static("", id="auth-error")
            with Horizontal(id="auth-buttons"):
                yield Button("Создать аккаунт", variant="primary", id="register")
                yield Button("Назад ко входу", id="back")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the first empty field."""
        for wid in ("pool", "user", "password"):
            field = self.query_one(f"#{wid}", Input)
            if not field.value:
                field.focus()
                return

    def on_input_changed(self, event: Input.Changed) -> None:
        """Check the login while it is typed."""
        if event.input.id != "user":
            return
        hint = ""
        if event.value.strip():
            try:
                validate_login(event.value.strip())
            except BadLoginError as exc:
                hint = str(exc)
        self.query_one("#login-hint", Static).update(hint)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter: to the next field; on the last one -- create the account."""
        if event.input.id == "comment":
            self.submit()
        else:
            self.focus_next()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Создать аккаунт / Назад ко входу."""
        if event.button.id == "register":
            self.submit()
        elif event.button.id == "back":
            self.dismiss(None)

    def action_back(self) -> None:
        """Esc: back to the login form."""
        self.dismiss(None)

    def submit(self) -> None:
        """Create the account with what is typed (in a thread)."""
        self.query_one("#auth-error", Static).update("Создаю аккаунт…")
        v = {w: self.query_one(f"#{w}", Input).value
             for w in ("pool", "user", "password", "password2", "group", "comment")}
        self._register(v)

    @work(thread=True, exclusive=True)
    def _register(self, v: dict[str, str]) -> None:
        url, user = v["pool"].strip(), v["user"].strip()
        try:
            token = account.register(self.env, url, user, v["password"], v["password2"],
                                     v["group"], v["comment"])
        except account.AuthError as exc:
            self.app.call_from_thread(self.query_one("#auth-error", Static).update, str(exc))
            return
        self.app.call_from_thread(self.dismiss, (url, user, token))
