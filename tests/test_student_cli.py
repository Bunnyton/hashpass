import pytest

from hashpass import student_cli


@pytest.mark.tier1
def test_no_subcommand_enters_task_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert student_cli.main([]) == 0
    assert "no tasks built yet" in capsys.readouterr().out


@pytest.mark.tier1
def test_list_prints_header(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert student_cli.main(["list"]) == 0
    assert "REF" in capsys.readouterr().out


@pytest.mark.tier1
def test_unknown_command_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        student_cli.main(["frobnicate"])
    assert exc.value.code != 0


@pytest.mark.tier1
def test_run_dispatches_to_cmd_run(tmp_path, monkeypatch):
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    seen = {}

    def fake_run(_env, ref) -> int:
        seen["ref"] = ref
        return 0

    monkeypatch.setattr(student_cli.cli, "cmd_run", fake_run)
    assert student_cli.main(["run", "lab:1"]) == 0
    assert seen["ref"] == "lab:1"
