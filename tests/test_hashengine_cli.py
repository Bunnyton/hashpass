import pytest

from hashengine import cli as engine_cli


@pytest.mark.tier1
def test_images_empty_env_prints_header(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert engine_cli.main(["images"]) == 0
    assert "Образ" in capsys.readouterr().out


@pytest.mark.tier1
def test_no_subcommand_prints_help(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert engine_cli.main([]) == 0
    assert "hashengine" in capsys.readouterr().out


@pytest.mark.tier1
def test_unknown_command_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        engine_cli.main(["frobnicate"])
    assert exc.value.code != 0


@pytest.mark.tier1
def test_refuses_when_not_activated(tmp_path, monkeypatch, capsys):
    # a plain student install has no activation marker -> hashengine refuses to run
    monkeypatch.delenv("HASHENGINE_ENABLE", raising=False)
    monkeypatch.setenv("HASHENGINE_HOME", str(tmp_path / "eng"))  # empty -> no engine.enabled
    assert engine_cli.main(["images"]) == 1
    assert "не активирован" in capsys.readouterr().err


@pytest.mark.tier1
def test_build_error_boundary_uses_engine_prog(tmp_path, monkeypatch, capsys):
    # a broken Taskfile exits 1 with a clean `hashengine:` message, never a traceback.
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert engine_cli.main(["build", str(tmp_path / "nope.Taskfile")]) == 1
    assert capsys.readouterr().err.startswith("hashengine:")


@pytest.mark.tier1
def test_push_base_dispatches_to_cmd_push_base(monkeypatch):
    from hashengine import cli as engine  # noqa: PLC0415
    calls = []
    monkeypatch.setattr(engine.cli, "cmd_push_base",
                        lambda env, registry=None, *, force=False:  # noqa: ARG005
                        calls.append((registry, force)) or 0)
    monkeypatch.setattr(engine_cli, "_engine_enabled", lambda: True)
    assert engine.main(["push", "base", "--force"]) == 0
    assert calls == [(None, True)]


@pytest.mark.tier1
def test_login_if_needed_dispatches_the_flag(monkeypatch):
    from hashengine import cli as engine  # noqa: PLC0415
    calls = []
    monkeypatch.setattr(engine.cli, "cmd_login",
                        lambda env, registry=None, *, if_needed=False:  # noqa: ARG005
                        calls.append((registry, if_needed)) or 0)
    monkeypatch.setattr(engine_cli, "_engine_enabled", lambda: True)
    assert engine.main(["login", "http://p", "--if-needed"]) == 0
    assert engine.main(["login", "http://p"]) == 0
    assert calls == [("http://p", True), ("http://p", False)]


@pytest.mark.tier1
def test_logout_dispatches_to_cmd_logout(monkeypatch):
    from hashengine import cli as engine  # noqa: PLC0415
    calls = []
    monkeypatch.setattr(engine.cli, "cmd_logout",
                        lambda env, registry=None: calls.append(registry) or 0)  # noqa: ARG005
    monkeypatch.setattr(engine_cli, "_engine_enabled", lambda: True)
    assert engine.main(["logout", "http://p"]) == 0
    assert engine.main(["logout"]) == 0
    assert calls == ["http://p", None]


@pytest.mark.tier1
def test_catalog_layout_dispatches(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(engine_cli.cli, "cmd_catalog_layout",
                        lambda env, specs, registry=None, io=None: calls.append((specs, registry)) or 0)  # noqa: ARG005
    monkeypatch.setattr(engine_cli, "_engine_enabled", lambda: True)
    assert engine_cli.main(["catalog", "layout", "--registry", "http://p", "Знакомство: a:1 b:1"]) == 0
    assert calls == [(["Знакомство: a:1 b:1"], "http://p")]
