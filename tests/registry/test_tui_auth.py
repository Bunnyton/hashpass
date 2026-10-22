"""Tier2: the TUI's login / sign-up / relogin forms and the solution viewer, on a live pool."""
import asyncio

import pytest
from textual.widgets import Input, Static

from hashpass import account
from hashpass.attempts import save_solution
from hashpass.auth_screens import LoginScreen, RegisterScreen
from hashpass.cli import Home
from hashpass.tui import PoolTUI, TaskRow
from hashpass.viewer import SolutionViewer


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_POOL", raising=False)
    return Home(tmp_path / "home")


async def _wait(pilot, cond, tries: int = 60) -> None:
    for _ in range(tries):
        if cond():
            return
        await pilot.pause(0.05)
    msg = "condition not reached"
    raise AssertionError(msg)


async def _type(pilot, app, wid: str, text: str) -> None:
    app.screen.query_one(f"#{wid}", Input).value = text
    await pilot.pause()


def _error(app) -> str:
    return str(app.screen.query_one("#auth-error", Static).render())


@pytest.mark.tier2
def test_signed_out_starts_on_login_and_wrong_password_stays(registry, env):
    registry.users.add("stud", "pass123!", role="student")

    async def drive() -> None:
        app = PoolTUI(env, registry.base_url, "", "")
        async with app.run_test(size=(100, 40)) as pilot:
            await _wait(pilot, lambda: isinstance(app.screen, LoginScreen))
            await pilot.press("tab")                       # Tab walks the form while signed out
            assert app.focused.id == "password"
            await _type(pilot, app, "user", "stud")
            await _type(pilot, app, "password", "wrong")
            await pilot.click("#login")
            await _wait(pilot, lambda: "Неверный логин или пароль" in _error(app))
            assert isinstance(app.screen, LoginScreen)
            assert not registry.users.has("ghost")
            await _type(pilot, app, "password", "pass123!")
            await pilot.click("#login")
            await _wait(pilot, lambda: not isinstance(app.screen, LoginScreen))
            assert app.user == "stud"
            assert app.token
            assert app.title == "hashpass · stud"
    asyncio.run(drive())


@pytest.mark.tier2
def test_register_button_creates_account(registry, env):
    async def drive() -> None:
        app = PoolTUI(env, registry.base_url, "", "")
        async with app.run_test(size=(100, 50)) as pilot:
            await _wait(pilot, lambda: isinstance(app.screen, LoginScreen))
            await pilot.click("#to-register")
            await _wait(pilot, lambda: isinstance(app.screen, RegisterScreen))
            await _type(pilot, app, "user", "bad login")
            assert "логин" in str(app.screen.query_one("#login-hint", Static).render()).lower()
            await _type(pilot, app, "user", "newbie")
            await _type(pilot, app, "password", "pass123!")
            await _type(pilot, app, "password2", "pass123?")
            app.screen.submit()
            await _wait(pilot, lambda: "Пароли не совпадают" in _error(app))
            await _type(pilot, app, "password2", "pass123!")
            await _type(pilot, app, "group", "G1")
            app.screen.submit()
            await _wait(pilot, lambda: app.user == "newbie"
                        and not isinstance(app.screen, (LoginScreen, RegisterScreen)))
            await pilot.pause(0.2)
            assert app.title == "hashpass · newbie"
            assert registry.users.has("newbie")
    asyncio.run(drive())


@pytest.mark.tier2
def test_relogin_and_deleted_account(registry, env):
    registry.users.add("stud", "pass123!", role="student")
    token = account.login(env, registry.base_url, "stud", "pass123!")

    async def drive() -> None:
        app = PoolTUI(env, registry.base_url, "stud", token)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            assert not isinstance(app.screen, LoginScreen)
            await pilot.press("L")
            await pilot.press("y")
            await _wait(pilot, lambda: isinstance(app.screen, LoginScreen))
            assert account.current(env)[2] == ""
            assert app.check_action("refresh", ()) is False
    asyncio.run(drive())

    registry.users.add("gone", "pass123!", role="student")
    tok = account.login(env, registry.base_url, "gone", "pass123!")
    registry.users.delete("gone")

    async def drive_gone() -> None:
        app = PoolTUI(env, registry.base_url, "gone", tok)
        async with app.run_test(size=(100, 40)) as pilot:
            await _wait(pilot, lambda: isinstance(app.screen, LoginScreen))
            assert "больше нет на пуле" in _error(app)
    asyncio.run(drive_gone())


@pytest.mark.tier2
def test_solution_key_opens_viewer(registry, env):
    registry.users.add("stud", "pass123!", role="student")
    token = account.login(env, registry.base_url, "stud", "pass123!")
    save_solution(env.root, "lab:1", {"ref": "lab:1", "updated": 0.0, "entries": [
        {"command": "ls [x]", "output": "a  b\n"}]})

    async def drive() -> None:
        app = PoolTUI(env, registry.base_url, "stud", token)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            row = TaskRow(ref="lab:1", number=1, block="", available=True, digest="",
                          server="passed", local=True, state="готово")
            app._cursor_row = lambda: row  # noqa: SLF001
            app.action_solution()
            await pilot.pause()
            assert isinstance(app.screen, SolutionViewer)
            text = app.screen.rendered().plain
            assert "$ ls [x]\na  b\n" in text
            await pilot.press("q")
            assert not isinstance(app.screen, SolutionViewer)
            row.server, row.local = None, False
            app.action_solution()
            await pilot.pause()
            assert not isinstance(app.screen, SolutionViewer)
    asyncio.run(drive())


@pytest.mark.tier1
@pytest.mark.parametrize("role", ["student", "admin"])
def test_footer_shows_solution_and_relogin_for_every_role(tmp_path, role):
    """User, 2026-10-16: «В футере нет» -- staff keys pushed p/L past the edge of the footer."""
    import html  # noqa: PLC0415
    import re  # noqa: PLC0415

    class _Pool:
        def catalog(self, *, token: str) -> list:  # noqa: ARG002
            return []

        def progress(self, *, token: str) -> dict:  # noqa: ARG002
            return {}

        def me(self, *, token: str) -> dict:  # noqa: ARG002
            return {"role": role}

    async def drive() -> None:
        app = PoolTUI(Home(tmp_path / "h"), "http://pool", "u", "tok")
        app.client = _Pool()
        async with app.run_test(size=(100, 30)) as pilot:
            footer = ""
            for _ in range(30):                      # the role arrives from me(): wait, don't guess
                await pilot.pause(0.1)
                text = html.unescape(re.sub(r"<[^>]+>", "", app.export_screenshot())).replace("\xa0", " ")
                footer = next((line for line in text.splitlines() if "Выход" in line), "")
                if "Решение" in footer and "Сменить аккаунт" in footer:
                    break
            assert "Решение" in footer
            assert "Сменить аккаунт" in footer
    asyncio.run(drive())
