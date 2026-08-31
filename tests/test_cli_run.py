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
def test_run_task_reference_solves_via_interact(tmp_path, base_tar):
    home = tmp_path / "home"
    (home / "base").mkdir(parents=True)
    (home / "base" / "rootfs.tar").write_bytes(base_tar.read_bytes())
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    tf = tmp_path / "Taskfile"
    tf.write_text(_TASK, encoding="utf-8")
    cli.cmd_build(env, str(tf))

    writes = []
    lines = iter(["grep -rh ERROR /var/log/app > /errors.txt", "exit"])
    io = cli.Io(read=lambda _p: next(lines, None), write=writes.append,
                clock=lambda: "2026-08-31T00:00:00")
    assert cli.cmd_run(env, "logtask:1", io) == 0
    assert any(w.startswith("✓ stage passed") for w in writes)
    assert "✓ all stages passed — task complete\n" in writes
