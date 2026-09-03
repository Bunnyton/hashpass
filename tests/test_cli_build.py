import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore

_TASK = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt
"""

_IMAGE = "image tool:1\nrun echo hi\n"


@pytest.mark.tier3
def test_cmd_build_task_then_image(tmp_path, base_tar, capsys, monkeypatch):
    home = tmp_path / "home"
    (home / "base").mkdir(parents=True)
    (home / "base" / "rootfs.tar").write_bytes(base_tar.read_bytes())  # skip docker export
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    # Image creation requires a login and namespaces the build under it; the push targets the
    # local service. Both are stubbed here so the build itself is what's under test.
    monkeypatch.setattr(cli, "_require_login", lambda _env, _io: "dev")
    monkeypatch.setattr(cli, "_push_image", lambda *_a, **_k: None)

    tf = tmp_path / "Taskfile"
    tf.write_text(_TASK, encoding="utf-8")
    assert cli.cmd_build(env, str(tf)) == 0
    assert "собрано: dev/logtask:1" in capsys.readouterr().out

    imf = tmp_path / "Imagefile"
    imf.write_text(_IMAGE, encoding="utf-8")
    assert cli.cmd_build(env, str(imf)) == 0
    assert "собрано: dev/tool:1" in capsys.readouterr().out

    store = ImageStore(env.images)
    assert store.list() == ["dev/logtask:1", "dev/tool:1"]
    assert cli._kind(store, "dev/logtask:1") == "task"  # noqa: SLF001
    assert cli._kind(store, "dev/tool:1") == "image"  # noqa: SLF001
