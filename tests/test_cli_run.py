
import pytest

from hashpass import cli

_TASK = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt
"""


@pytest.mark.tier3
def test_run_task_grades_in_background(tmp_path, base_tar, monkeypatch):
    home = tmp_path / "home"
    (home / "base").mkdir(parents=True)
    (home / "base" / "rootfs.tar").write_bytes(base_tar.read_bytes())  # seed the base tar (skip docker)
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    tf = tmp_path / "Taskfile"
    tf.write_text(_TASK, encoding="utf-8")
    cli.cmd_build(env, str(tf))

    # In place of the interactive foreground console, simulate the student running the
    # solve command in the student's mount; grading on exit must then advance the stage.
    def solve_in_console(runner: object, _binds: object = None) -> None:
        runner.run(["sh", "-c", "grep -rh ERROR /var/log/app > /errors.txt"])
    monkeypatch.setattr(cli, "_interactive_console", solve_in_console)

    writes = []
    io = cli.Io(read=lambda _p: None, write=writes.append, clock=lambda: "2026-08-31T00:00:00")
    assert cli.cmd_run(env, "logtask:1", io) == 0
    assert any("✓ stage passed" in w for w in writes)
    assert "✓ all stages passed — task complete\n" in writes
