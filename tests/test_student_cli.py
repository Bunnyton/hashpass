"""Tier1: student CLI dispatch routing (each sub-command reaches the right cli function)."""
import pytest

from hashpass import student_cli


@pytest.fixture
def fake_env(monkeypatch) -> None:
    monkeypatch.setattr(student_cli.cli, "build_env", lambda *_a, **_k: "ENV")


@pytest.mark.tier1
@pytest.mark.usefixtures("fake_env")
def test_no_subcommand_calls_pool_home(monkeypatch):
    seen = {}
    monkeypatch.setattr(student_cli.cli, "cmd_pool_home",
                        lambda env: seen.update(env=env) or 0)
    assert student_cli.main([]) == 0
    assert seen["env"] == "ENV"


@pytest.mark.tier1
@pytest.mark.usefixtures("fake_env")
def test_run_calls_pool_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(student_cli.cli, "cmd_pool_run",
                        lambda _env, arg: seen.update(arg=arg) or 0)
    assert student_cli.main(["run", "3"]) == 0
    assert seen["arg"] == "3"


@pytest.mark.tier1
@pytest.mark.usefixtures("fake_env")
def test_register_login_pull_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(student_cli.cli, "cmd_register",
                        lambda _env, pool: calls.append(("reg", pool)) or 0)
    monkeypatch.setattr(student_cli.cli, "cmd_pool_login",
                        lambda _env, pool: calls.append(("login", pool)) or 0)
    monkeypatch.setattr(student_cli.cli, "cmd_pool_pull",
                        lambda _env: calls.append(("pull",)) or 0)
    assert student_cli.main(["register", "--pool", "http://p"]) == 0
    assert student_cli.main(["login"]) == 0
    assert student_cli.main(["pull"]) == 0
    assert calls == [("reg", "http://p"), ("login", None), ("pull",)]


@pytest.mark.tier1
def test_unknown_command_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        student_cli.main(["frobnicate"])
    assert exc.value.code != 0
