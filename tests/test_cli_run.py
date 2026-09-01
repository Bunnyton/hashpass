import subprocess

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

    # In place of the interactive fish shell, simulate the student running the solve
    # command inside the booted machine; the background grader must then advance.
    def solve_in_machine(machine: str) -> None:
        subprocess.run(["sudo", "machinectl", "shell", machine, "/bin/sh", "-c",
                        "grep -rh ERROR /var/log/app > /errors.txt"], check=False)
    monkeypatch.setattr(cli, "_interactive_shell", solve_in_machine)

    writes = []
    io = cli.Io(read=lambda _p: None, write=writes.append, clock=lambda: "2026-08-31T00:00:00")
    assert cli.cmd_run(env, "logtask:1", io) == 0
    assert any("✓ stage passed" in w for w in writes)
    assert "✓ all stages passed — task complete\n" in writes
