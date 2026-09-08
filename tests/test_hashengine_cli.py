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
