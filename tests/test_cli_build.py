import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore

_TASK = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage

  "collect ERROR lines"
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


def _fake_build_pipeline(monkeypatch, tmp_path) -> None:
    """Stub the nspawn build: `build` just stores an empty layer under the recipe's ref."""
    def fake_build(recipe, store, *, base, workdir, progress) -> object:  # noqa: ARG001
        src = tmp_path / "fake-layer"
        src.mkdir(exist_ok=True)
        return store.save(recipe.name, recipe.version, src, ())
    monkeypatch.setattr(cli, "ensure_base_image", lambda _env, _store, **_kw: tmp_path)
    monkeypatch.setattr(cli, "build", fake_build)
    monkeypatch.setattr(cli, "_reset_workdir", lambda _p: None)


@pytest.mark.tier1
def test_cmd_build_with_a_pool_configured_hints_push_and_never_pushes_locally(tmp_path, monkeypatch):
    _fake_build_pipeline(monkeypatch, tmp_path)
    monkeypatch.setenv("HASHPASS_POOL", "http://pool.example:8080")
    monkeypatch.setattr(cli, "_author_identity", lambda _env, _io: "bunnyton")
    monkeypatch.setattr(cli, "_push_image", lambda *_a, **_k: pytest.fail("must not push to the local service"))
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    imf = tmp_path / "Imagefile"
    imf.write_text(_IMAGE, encoding="utf-8")
    out: list[str] = []
    io = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    assert cli.cmd_build(env, str(imf), io=io) == 0
    assert any("hashengine push bunnyton/tool:1" in s for s in out)


@pytest.mark.tier1
def test_cmd_build_without_a_pool_pushes_to_the_local_service(tmp_path, monkeypatch):
    _fake_build_pipeline(monkeypatch, tmp_path)
    monkeypatch.delenv("HASHPASS_POOL", raising=False)
    monkeypatch.setattr(cli, "_author_identity", lambda _env, _io: "dev")
    pushed: list[str] = []
    monkeypatch.setattr(cli, "_push_image", lambda _env, _store, ref, _io: pushed.append(ref))
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    imf = tmp_path / "Imagefile"
    imf.write_text(_IMAGE, encoding="utf-8")
    assert cli.cmd_build(env, str(imf), io=cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "")) == 0
    assert pushed == ["dev/tool:1"]


@pytest.mark.tier1
def test_build_key_changes_when_a_parent_is_rebuilt(tmp_path):
    # A child chained with `from` must not be served from the cache once its parent changed:
    # the key folds each parent's own build_key (or pool digest) in, not just its ref.
    from hashpass.build import _build_key, _parent_ids  # noqa: PLC0415
    store = ImageStore(tmp_path / "images")
    src = tmp_path / "src"
    src.mkdir()
    base = tmp_path / "base"
    (base / "etc").mkdir(parents=True)
    (base / "etc" / "hp-base-version").write_text("19\n", encoding="utf-8")
    store.save("bunnyton/apt-update", "1", src, (), build_key="k1")
    first = _build_key(base, _parent_ids(store, ("bunnyton/apt-update:1",)), ())
    store.save("bunnyton/apt-update", "1", src, (), build_key="k2")     # parent rebuilt
    second = _build_key(base, _parent_ids(store, ("bunnyton/apt-update:1",)), ())
    assert first != second
    assert _parent_ids(store, ("bunnyton/apt-update:1",)) == ("bunnyton/apt-update:1@k2",)


@pytest.mark.tier1
def test_cmd_build_namespaces_bare_from_parents_like_the_image_itself(tmp_path, monkeypatch):
    # `from apt-update:1` in a course Taskfile must resolve to the owner's own build of that
    # task (`bunnyton/apt-update:1`), exactly as the image name itself is namespaced.
    seen: list[tuple[str, ...]] = []

    def fake_build(recipe, store, *, base, workdir, progress) -> object:  # noqa: ARG001
        seen.append(recipe.parents)
        src = tmp_path / "fake-layer"
        src.mkdir(exist_ok=True)
        return store.save(recipe.name, recipe.version, src, recipe.parents)
    monkeypatch.setattr(cli, "ensure_base_image", lambda _env, _store, **_kw: tmp_path)
    monkeypatch.setattr(cli, "build", fake_build)
    monkeypatch.setattr(cli, "_reset_workdir", lambda _p: None)
    monkeypatch.setattr(cli, "_author_identity", lambda _env, _io: "bunnyton")
    monkeypatch.setattr(cli, "_push_image", lambda *_a, **_k: None)
    monkeypatch.delenv("HASHPASS_POOL", raising=False)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    imf = tmp_path / "Imagefile"
    imf.write_text("image apt-remove:1\nfrom apt-update:1, alice/lib:2\nrun echo hi\n", encoding="utf-8")
    assert cli.cmd_build(env, str(imf), io=cli.Io(read=lambda _p: None, write=lambda _s: None,
                                                   clock=lambda: "")) == 0
    assert seen == [("bunnyton/apt-update:1", "alice/lib:2")]   # bare -> owner; explicit ns kept
