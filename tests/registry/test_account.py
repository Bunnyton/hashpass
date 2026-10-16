"""Tier2: account.login/register/logout against a live pool -- the TUI forms' backend."""
import pytest

from hashpass import account
from hashpass.cli import Home, load_pool
from hashpass.registry.remote import RemoteRegistry


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_POOL", raising=False)
    return Home(tmp_path / "home")


@pytest.mark.tier2
def test_register_then_login_then_logout(registry, env):
    url = registry.base_url
    assert account.register(env, url, "stud", "pass123!", "pass123!", "G", "c")
    assert account.current(env)[:2] == (url, "stud")
    account.logout(env, url)
    assert account.current(env) == (url, "", "")
    assert load_pool(env)["user"] == ""
    assert account.login(env, url, "stud", "pass123!")
    assert account.current(env)[1] == "stud"


@pytest.mark.tier2
def test_wrong_password_does_not_register(registry, env):
    registry.users.add("stud", "pass123!", role="student")
    with pytest.raises(account.AuthError, match="Неверный логин или пароль"):
        account.login(env, registry.base_url, "stud", "nope")
    with pytest.raises(account.AuthError, match="Неверный логин или пароль"):
        account.login(env, registry.base_url, "ghost", "pass123!")
    assert not registry.users.has("ghost")


@pytest.mark.tier2
@pytest.mark.parametrize(("user", "pw", "pw2", "msg"), [
    ("stud", "pass123!", "pass123?", "Пароли не совпадают"),
    ("stud", "short", "short", "пароль"),
    ("bad login", "pass123!", "pass123!", "логин"),
    ("", "pass123!", "pass123!", "Введите логин"),
])
def test_register_form_errors(registry, env, user, pw, pw2, msg):  # noqa: PLR0913, PLR0917
    with pytest.raises(account.AuthError, match=msg):
        account.register(env, registry.base_url, user, pw, pw2)


@pytest.mark.tier2
def test_register_taken_and_closed(registry, env):
    registry.users.add("stud", "pass123!", role="student")
    with pytest.raises(account.AuthError, match="уже занят"):
        account.register(env, registry.base_url, "stud", "pass123!", "pass123!")
    registry.users.add("adm", "pass123!", role="admin")
    admin = RemoteRegistry(registry.base_url)
    admin._post_json("/admin/registration", {"open": False},  # noqa: SLF001
                     token=admin.login("adm", "pass123!"))
    with pytest.raises(account.AuthError, match="Регистрация на пуле закрыта"):
        account.register(env, registry.base_url, "new", "pass123!", "pass123!")


@pytest.mark.tier2
def test_pool_down(env):
    with pytest.raises(account.AuthError, match="Пул недоступен"):
        account.login(env, "http://127.0.0.1:9", "stud", "pass123!")
