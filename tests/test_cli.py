from pathlib import Path

import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore


@pytest.mark.tier1
def test_resolve_root_prefers_env_then_default_home(tmp_path):
    assert cli.resolve_root({"HASHPASS_HOME": "/x/y"},
                            default_home=tmp_path) == __import__("pathlib").Path("/x/y")
    assert cli.resolve_root({}, default_home=tmp_path) == tmp_path / ".hashpass"


@pytest.mark.tier1
def test_home_sub_paths():
    h = cli.Home(Path("/home/u/.hashpass"))
    assert h.images == Path("/home/u/.hashpass/images")
    assert h.base_tar == Path("/home/u/.hashpass/base/rootfs.tar")
    assert h.creds == Path("/home/u/.hashpass/creds.json")
    assert h.work == Path("/home/u/.hashpass/work")


@pytest.mark.tier1
def test_build_env_creates_images_dir(tmp_path):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    assert env.images.is_dir()


class _Completed:
    stdout = "cid123\n"


@pytest.mark.tier1
def test_ensure_base_tar_shortcircuits_when_present(tmp_path):
    dest = tmp_path / "rootfs.tar"
    dest.write_text("x", encoding="utf-8")
    calls = []
    cli.ensure_base_tar(dest, run=lambda *a, **_k: calls.append(a), which=lambda _n: "docker")
    assert calls == []


@pytest.mark.tier1
def test_ensure_base_tar_requires_docker(tmp_path):
    with pytest.raises(RuntimeError, match="docker is required"):
        cli.ensure_base_tar(tmp_path / "base" / "rootfs.tar",
                            run=lambda *_a, **_k: _Completed(), which=lambda _n: None)


@pytest.mark.tier1
def test_ensure_base_tar_export_argv(tmp_path):
    dest = tmp_path / "base" / "rootfs.tar"
    calls = []

    def fake_run(argv: list, **_kwargs: object) -> _Completed:
        calls.append(argv)
        return _Completed()

    cli.ensure_base_tar(dest, run=fake_run, which=lambda _n: "/usr/bin/docker")
    assert calls[0] == ["docker", "create", "debian:trixie-slim"]
    assert calls[1] == ["docker", "export", "cid123", "-o", str(dest)]
    assert calls[2] == ["docker", "rm", "cid123"]
    assert dest.parent.exists()


def _seed_image(store: ImageStore, tmp_path, name: str, *, task: bool = False) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, "1", src, ())
    if task:
        (store.get(f"{name}:1").layer.parent / "task").mkdir()


@pytest.mark.tier1
def test_format_image_rows_empty_is_header_only():
    assert cli.format_image_rows([]) == "REF  KIND\n"


@pytest.mark.tier1
def test_format_image_rows_aligns_columns():
    out = cli.format_image_rows([("log-archive:1", "task"), ("base:latest", "image")])
    assert out == ("REF            KIND\n"
                   "log-archive:1  task\n"
                   "base:latest    image\n")


@pytest.mark.tier1
def test_kind_detects_task_vs_image(tmp_path):
    store = ImageStore(tmp_path / "images")
    _seed_image(store, tmp_path, "base")
    _seed_image(store, tmp_path, "lab", task=True)
    assert cli._kind(store, "lab:1") == "task"  # noqa: SLF001
    assert cli._kind(store, "base:1") == "image"  # noqa: SLF001


@pytest.mark.tier1
def test_cmd_images_prints_table(tmp_path, capsys):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    store = ImageStore(env.images)
    _seed_image(store, tmp_path, "base")
    _seed_image(store, tmp_path, "lab", task=True)
    assert cli.cmd_images(env) == 0
    out = capsys.readouterr().out
    assert out == cli.format_image_rows([("base:1", "image"), ("lab:1", "task")])
