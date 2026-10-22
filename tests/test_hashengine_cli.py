"""Tier1: `hashengine` is an alias of the one `hashpass` binary (spec 2026-10-23 §1)."""
import pytest

from hashengine import cli as engine_cli
from hashpass import student_cli


@pytest.mark.tier1
def test_images_through_the_alias_says_where_it_moved(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HASHENGINE_ENABLE", raising=False)          # no activation needed any more
    monkeypatch.setenv("HASHENGINE_HOME", str(tmp_path / "eng"))
    assert engine_cli.main(["images"]) == 0
    out = capsys.readouterr()
    assert "Образ" in out.out and "hashpass images" in out.err


@pytest.mark.tier1
def test_no_subcommand_without_a_terminal_prints_help(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert engine_cli.main([]) == 0
    assert "usage: hashpass" in capsys.readouterr().out


@pytest.mark.tier1
def test_unknown_command_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        engine_cli.main(["frobnicate"])
    assert exc.value.code != 0


@pytest.mark.tier1
def test_build_error_boundary(tmp_path, monkeypatch, capsys):
    # a broken Taskfile exits 1 with a clean `hashpass:` message, never a traceback.
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert engine_cli.main(["build", str(tmp_path / "nope.Taskfile")]) == 1
    assert "hashpass:" in capsys.readouterr().err


@pytest.mark.tier1
def test_push_base_dispatches_to_cmd_push_base(monkeypatch):
    calls = []
    monkeypatch.setattr(student_cli.cli, "cmd_push_base",
                        lambda env, registry=None, *, force=False:  # noqa: ARG005
                        calls.append((registry, force)) or 0)
    assert engine_cli.main(["push", "base", "--force"]) == 0
    assert calls == [(None, True)]


@pytest.mark.tier1
def test_login_if_needed_for_scripts_plain_login_for_people(monkeypatch):
    calls = []
    monkeypatch.setattr(student_cli.cli, "cmd_login",
                        lambda env, registry=None, *, if_needed=False:  # noqa: ARG005
                        calls.append(("script", registry, if_needed)) or 0)
    monkeypatch.setattr(student_cli.cli, "cmd_pool_login",
                        lambda env, pool=None: calls.append(("person", pool)) or 0)  # noqa: ARG005
    assert engine_cli.main(["login", "http://p", "--if-needed"]) == 0
    assert student_cli.main(["login", "http://p"]) == 0
    assert calls == [("script", "http://p", True), ("person", "http://p")]


@pytest.mark.tier1
def test_logout_dispatches_to_cmd_logout(monkeypatch):
    calls = []
    monkeypatch.setattr(student_cli.cli, "cmd_logout",
                        lambda env, registry=None: calls.append(registry) or 0)  # noqa: ARG005
    assert engine_cli.main(["logout", "http://p"]) == 0
    assert student_cli.main(["logout"]) == 0
    assert calls == ["http://p", None]


@pytest.mark.tier1
def test_catalog_layout_dispatches(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(student_cli.cli, "cmd_catalog_layout",
                        lambda env, specs, registry=None, io=None: calls.append((specs, registry)) or 0)  # noqa: ARG005
    assert engine_cli.main(["catalog", "layout", "--registry", "http://p", "Знакомство: a:1 b:1"]) == 0
    assert calls == [(["Знакомство: a:1 b:1"], "http://p")]


@pytest.mark.tier1
def test_one_binary_has_every_command():
    p = student_cli.build_parser()
    assert p.parse_args(["push", "x:1", "-m", "фикс"]).message == "фикс"
    assert p.parse_args(["clone", "alice/lab:1", "dir"]).dest == "dir"
    assert p.parse_args(["pull"]).ref is None and p.parse_args(["pull", "x:1"]).ref == "x:1"
    assert p.parse_args(["run", "3"]).task == "3"
    for cmd in (["work"], ["build", "T"], ["serve"], ["tag", "x:1", "s"], ["rm", "x:1_v1"], ["fork", "a/b:1"],
                ["images"], ["remote"], ["migrate-courses"], ["search", "git"], ["add", "a/b"]):
        assert p.parse_args(cmd).command == cmd[0]
