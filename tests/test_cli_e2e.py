import subprocess

import pytest

from hashpass import cli

_TASK = """\
image e2e:1
run mkdir -p /var/log/app
run printf 'ERROR x\\nok\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt
"""


@pytest.mark.tier3
def test_build_via_main_then_scripted_run(tmp_path, base_tar, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / "base").mkdir(parents=True)
    (home / "base" / "rootfs.tar").write_bytes(base_tar.read_bytes())
    monkeypatch.setenv("HASHPASS_HOME", str(home))
    tf = tmp_path / "Taskfile"
    tf.write_text(_TASK, encoding="utf-8")

    assert cli.main(["build", str(tf)]) == 0
    assert "built task e2e:1" in capsys.readouterr().out
    assert cli.main(["images"]) == 0
    assert "e2e:1" in capsys.readouterr().out

    # The interactive run drops into fish; simulate the student's solve in the booted
    # machine and let the background grader complete the task.
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)

    def solve_in_machine(machine: str) -> None:
        subprocess.run(["sudo", "machinectl", "shell", machine, "/bin/sh", "-c",
                        "grep -rh ERROR /var/log/app > /errors.txt"], check=False)
    monkeypatch.setattr(cli, "_interactive_shell", solve_in_machine)

    writes = []
    io = cli.Io(read=lambda _p: None, write=writes.append, clock=lambda: "t")
    assert cli.cmd_run(env, "e2e:1", io) == 0
    assert "✓ all stages passed — task complete\n" in writes
