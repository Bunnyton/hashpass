import gzip
import io
import json
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry import blob as blobmod
from hashpass.registry.blob import (
    ImageBlobInfo,
    inspect_image_blob,
    pack_image,
    pack_image_to_file,
    unpack_image,
    unpack_image_file,
)


@pytest.mark.tier1
def test_unpack_rejects_traversing_meta_name(tmp_path):
    # A hostile registry (anonymous pull) or a malicious authenticated pusher could craft a blob
    # whose meta.json declares a traversing name — it must be refused, writing nothing outside.
    layer = tmp_path / "layer"
    layer.mkdir()
    (layer / "f.txt").write_text("x", encoding="utf-8")
    buf = io.BytesIO()
    meta = json.dumps({"name": "../evil", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
        tar.add(layer, arcname="layer")
    store = ImageStore(tmp_path / "images")
    with pytest.raises(ValueError, match="unsafe image"):
        unpack_image(buf.getvalue(), store)
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path.parent / "evil").exists()


@pytest.mark.tier1
def test_blob_pack_unpack_roundtrip(tmp_path):
    layer = tmp_path / "layer"
    (layer / "d").mkdir(parents=True)
    (layer / "a.txt").write_text("hello", encoding="utf-8")
    (layer / "d" / "b.txt").write_text("nested", encoding="utf-8")
    src = ImageStore(tmp_path / "src")
    img = src.save("web", "3", layer, ("base:1", "extra:2"))

    ref = unpack_image(pack_image(img), ImageStore(tmp_path / "dst"))
    assert ref == "web:3"
    got = ImageStore(tmp_path / "dst").get("web:3")
    assert (got.layer / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (got.layer / "d" / "b.txt").read_text(encoding="utf-8") == "nested"
    assert got.parents == ("base:1", "extra:2")


def _raw_tar(tmp_path: Path, members: list[tuple[str, bytes | None, int, int]],
             meta: dict | None = None, *, gz: bool = False) -> Path:
    """Build a blob by hand: members = (name, data|None for dir, mode, uid)."""
    path = tmp_path / ("hand.tar.gz" if gz else "hand.tar")
    meta_b = json.dumps(meta or {"name": "app", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(path, mode="w:gz" if gz else "w") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta_b)
        tar.addfile(info, io.BytesIO(meta_b))
        for name, data, mode, uid in members:
            ti = tarfile.TarInfo(name)
            ti.mode, ti.uid = mode, uid
            if data is None:
                ti.type = tarfile.DIRTYPE
                tar.addfile(ti)
            else:
                ti.size = len(data)
                tar.addfile(ti, io.BytesIO(data))
    return path


@pytest.mark.tier1
def test_pack_to_file_is_gzip_and_roundtrips(tmp_path):
    layer = tmp_path / "layer"
    (layer / "d").mkdir(parents=True)
    (layer / "a.txt").write_text("hello", encoding="utf-8")
    img = ImageStore(tmp_path / "src").save("web", "3", layer, ("base:1",))
    blob = pack_image_to_file(img, tmp_path / "web.tar.gz")
    with gzip.open(blob, "rb") as f:                     # really gzip
        assert f.read(2)
    info = inspect_image_blob(blob)
    assert info == ImageBlobInfo("web", "3", ("base:1",), needs_root=False)
    dst = ImageStore(tmp_path / "dst")
    assert unpack_image_file(blob, dst) == "web:3"
    assert (dst.get("web:3").layer / "a.txt").read_text(encoding="utf-8") == "hello"
    assert pack_image(img)[:2] == b"\x1f\x8b"             # bytes wrapper is gzip too


@pytest.mark.tier1
def test_unpack_reads_legacy_plain_tar(tmp_path):
    blob = _raw_tar(tmp_path, [("layer", None, 0o755, 1000), ("layer/f.txt", b"x", 0o644, 1000)])
    dst = ImageStore(tmp_path / "dst")
    assert unpack_image_file(blob, dst) == "app:1"
    assert unpack_image(blob.read_bytes(), ImageStore(tmp_path / "dst2")) == "app:1"


@pytest.mark.tier1
def test_inspect_rejects_missing_layer_and_members_outside_layer(tmp_path):
    with pytest.raises(ValueError, match="no layer"):
        inspect_image_blob(_raw_tar(tmp_path, []))
    with pytest.raises(ValueError, match="outside layer"):
        inspect_image_blob(_raw_tar(tmp_path, [("layer", None, 0o755, 0), ("etc/passwd", b"", 0o644, 0)]))
    with pytest.raises(ValueError, match="unsafe"):
        inspect_image_blob(_raw_tar(tmp_path, [("layer", None, 0o755, 0), ("layer/../x", b"", 0o644, 0)]))
    with pytest.raises(ValueError, match="unsafe image"):
        inspect_image_blob(_raw_tar(tmp_path, [("layer", None, 0o755, 0)],
                                    meta={"name": "../evil", "version": "1", "parents": []}))
    # Test no meta.json with valid layer directory
    path = tmp_path / "nometa.tar"
    with tarfile.open(path, "w") as tar:
        layer_info = tarfile.TarInfo("layer")
        layer_info.type = tarfile.DIRTYPE
        tar.addfile(layer_info)
    with pytest.raises(ValueError, match="no meta"):
        inspect_image_blob(path)


@pytest.mark.tier1
def test_inspect_rejects_layer_as_file(tmp_path):
    """A blob with a FILE member named 'layer' (not directory) must be rejected."""
    path = tmp_path / "bad_layer.tar"
    meta_b = json.dumps({"name": "app", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(path, mode="w") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta_b)
        tar.addfile(info, io.BytesIO(meta_b))
        # Add a FILE named "layer" instead of a directory
        layer_info = tarfile.TarInfo("layer")
        layer_info.size = 4
        tar.addfile(layer_info, io.BytesIO(b"test"))
    with pytest.raises(ValueError, match="no layer"):
        inspect_image_blob(path)


@pytest.mark.tier1
def test_inspect_needs_root_on_uid0_or_setuid(tmp_path):
    plain = _raw_tar(tmp_path, [("layer", None, 0o755, 1000), ("layer/f", b"", 0o644, 1000)])
    assert inspect_image_blob(plain).needs_root is False
    root_owned = _raw_tar(tmp_path, [("layer", None, 0o755, 0), ("layer/f", b"", 0o644, 1000)])
    assert inspect_image_blob(root_owned).needs_root is True
    suid = _raw_tar(tmp_path, [("layer", None, 0o755, 1000),
                               ("layer/sudo", b"", 0o755 | stat.S_ISUID, 1000)], gz=True)
    assert inspect_image_blob(suid).needs_root is True


def _fake_run_factory(calls: list[list[str]], *, fail_rsync: bool = False,  # noqa: ANN202
                      fail_tar: bool = False):
    def fake_run(cmd, **kwargs):  # noqa: ANN202, ANN003, ARG001
        calls.append(list(cmd))
        if cmd[:2] == ["sudo", "tar"]:
            # emulate `tar -x ... --strip-components=1 -C <incoming> layer`: create a file there
            incoming = Path(cmd[cmd.index("-C") + 1])
            (incoming / "from-tar.txt").write_text("root-owned in real life", encoding="utf-8")
            if fail_tar:                            # a partial tree is left behind, like ENOSPC
                raise subprocess.CalledProcessError(
                    2, cmd, b"", b"tar: layer/big: Cannot write: No space left on device\n")
        if cmd[:2] == ["sudo", "rsync"]:
            if fail_rsync:
                raise subprocess.CalledProcessError(1, cmd)
            target = Path(cmd[-1].rstrip("/"))
            for child in target.iterdir():          # emulate `--delete` from an empty source
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    return fake_run


@pytest.mark.tier1
def test_sudo_unpack_swaps_layer_atomically_and_cleans_old(tmp_path, monkeypatch):
    blob = _raw_tar(tmp_path, [("layer", None, 0o755, 0), ("layer/f", b"", 0o644, 0)], gz=True)
    store = ImageStore(tmp_path / "dst")
    old_layer = store.dir("app", "1") / "layer"
    old_layer.mkdir(parents=True)
    (old_layer / "stale.txt").write_text("old", encoding="utf-8")
    store.write_meta("app", "1", parents=())
    calls: list[list[str]] = []
    monkeypatch.setattr(blobmod.subprocess, "run", _fake_run_factory(calls))
    assert unpack_image_file(blob, store, sudo=True) == "app:1"
    layer = store.dir("app", "1") / "layer"
    assert (layer / "from-tar.txt").exists() and not (layer / "stale.txt").exists()
    assert calls[0][:4] == ["sudo", "tar", "-xpf", str(blob)]
    assert "--same-owner" in calls[0] and "--strip-components=1" in calls[0] and calls[0][-1] == "layer"
    assert calls[1][:3] == ["sudo", "rsync", "-a"] and "--delete" in calls[1]
    assert not list(store.dir("app", "1").glob("layer.old-*"))         # removed after rsync-empty
    assert not list(store.dir("app", "1").glob("layer.incoming-*"))


@pytest.mark.tier1
def test_leftover_old_layers_are_cleaned_on_next_unpack(tmp_path, monkeypatch):
    blob = _raw_tar(tmp_path, [("layer", None, 0o755, 0), ("layer/f", b"", 0o644, 0)], gz=True)
    store = ImageStore(tmp_path / "dst")
    (store.dir("app", "1") / "layer").mkdir(parents=True)
    store.write_meta("app", "1", parents=())
    calls: list[list[str]] = []
    monkeypatch.setattr(blobmod.subprocess, "run", _fake_run_factory(calls, fail_rsync=True))
    unpack_image_file(blob, store, sudo=True)                          # cleanup fails, unpack succeeds
    leftovers = list(store.dir("app", "1").glob("layer.old-*"))
    assert len(leftovers) == 1 and (store.dir("app", "1") / "layer" / "from-tar.txt").exists()
    calls.clear()
    monkeypatch.setattr(blobmod.subprocess, "run", _fake_run_factory(calls))
    unpack_image_file(blob, store, sudo=True)                          # next pull sweeps both old dirs
    assert not list(store.dir("app", "1").glob("layer.old-*"))
    assert sum(1 for c in calls if c[:2] == ["sudo", "rsync"]) == 2  # noqa: PLR2004


def _link_tar(tmp_path: Path, members: list[tarfile.TarInfo | tuple[str, bytes | None]],
              meta: dict | None = None) -> Path:
    """Build a blob from ready TarInfos (links, devices) and (name, data|None-for-dir) tuples."""
    path = tmp_path / "links.tar"
    meta_b = json.dumps(meta or {"name": "app", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(path, mode="w") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta_b)
        tar.addfile(info, io.BytesIO(meta_b))
        layer = tarfile.TarInfo("layer")
        layer.type, layer.mode, layer.uid = tarfile.DIRTYPE, 0o755, 1000
        tar.addfile(layer)
        for m in members:
            if isinstance(m, tarfile.TarInfo):
                tar.addfile(m)
                continue
            name, data = m
            ti = tarfile.TarInfo(name)
            ti.mode, ti.uid = 0o644, 1000
            if data is None:
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(ti)
            else:
                ti.size = len(data)
                tar.addfile(ti, io.BytesIO(data))
    return path


def _link(name: str, target: str, kind: bytes = tarfile.SYMTYPE) -> tarfile.TarInfo:
    ti = tarfile.TarInfo(name)
    ti.type, ti.linkname, ti.mode, ti.uid = kind, target, 0o777, 1000
    return ti


@pytest.mark.tier1
def test_inspect_rejects_member_under_symlink_ancestor(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    blob = _link_tar(tmp_path, [_link("layer/d", str(outside)), ("layer/d/owned.txt", b"pwned")])
    with pytest.raises(ValueError, match="symlink ancestor"):
        inspect_image_blob(blob)
    store = ImageStore(tmp_path / "images")
    with pytest.raises(ValueError, match="symlink ancestor"):
        unpack_image_file(blob, store)                  # non-sudo (tarfile) path
    assert not (outside / "owned.txt").exists()
    assert not list(outside.iterdir())
    assert not store.exists("app:1")


@pytest.mark.tier1
def test_inspect_rejects_regular_file_over_a_symlink_member(tmp_path):
    # Same name twice: the file would be written THROUGH the already-extracted symlink.
    blob = _link_tar(tmp_path, [_link("layer/f", "/opt/x"), ("layer/f", b"pwned")])
    with pytest.raises(ValueError, match="symlink ancestor"):
        inspect_image_blob(blob)


@pytest.mark.tier1
def test_inspect_rejects_member_under_hardlink(tmp_path):
    blob = _link_tar(tmp_path, [("layer/a", b"x"), _link("layer/h", "layer/a", tarfile.LNKTYPE),
                                ("layer/h/x", b"y")])
    with pytest.raises(ValueError, match="symlink ancestor"):
        inspect_image_blob(blob)


@pytest.mark.tier1
def test_inspect_rejects_escaping_hardlink(tmp_path):
    for target in ("/etc/shadow", "etc/passwd", "layer/../../x", "layerx/y"):
        blob = _link_tar(tmp_path, [_link("layer/h", target, tarfile.LNKTYPE)])
        with pytest.raises(ValueError, match="hardlink"):
            inspect_image_blob(blob)


@pytest.mark.tier1
def test_inspect_rejects_hardlink_to_a_symlink_member(tmp_path):
    # os.link follows symlinks: a hardlink to layer/s would pin whatever s points at.
    blob = _link_tar(tmp_path, [_link("layer/s", "/home/student/.bashrc"),
                                _link("layer/h", "layer/s", tarfile.LNKTYPE)])
    with pytest.raises(ValueError, match="hardlink"):
        inspect_image_blob(blob)


@pytest.mark.tier1
@pytest.mark.parametrize("kind", [tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE])
def test_inspect_rejects_device_and_fifo_members(tmp_path, kind):
    dev = tarfile.TarInfo("layer/dev")
    dev.type, dev.mode, dev.uid, dev.devmajor, dev.devminor = kind, 0o666, 0, 1, 3
    with pytest.raises(ValueError, match="device"):
        inspect_image_blob(_link_tar(tmp_path, [dev]))


@pytest.mark.tier1
def test_absolute_symlink_without_children_is_accepted(tmp_path):
    # dpkg ships absolute symlinks (/etc/alternatives/*): they stay allowed.
    blob = _link_tar(tmp_path, [("layer/usr", None), ("layer/usr/bin", None),
                                _link("layer/usr/bin/editor", "/etc/alternatives/editor"),
                                _link("layer/usr/bin/vi", "editor"),
                                ("layer/a", b"x"), _link("layer/b", "layer/a", tarfile.LNKTYPE)])
    assert inspect_image_blob(blob).name == "app"
    store = ImageStore(tmp_path / "images")
    assert unpack_image_file(blob, store) == "app:1"
    link = store.get("app:1").layer / "usr" / "bin" / "editor"
    assert link.is_symlink() and str(link.readlink()) == "/etc/alternatives/editor"


@pytest.mark.tier1
@pytest.mark.parametrize("parent", ["../x:1", "a/../../b", "ok:../1", "/abs:1"])
def test_inspect_rejects_unsafe_parents(tmp_path, parent):
    blob = _link_tar(tmp_path, [("layer/a", b"x")],
                     meta={"name": "app", "version": "1", "parents": ["base:1", parent]})
    with pytest.raises(ValueError, match="unsafe image"):
        inspect_image_blob(blob)


@pytest.mark.tier1
def test_overlay_whiteout_char_device_is_accepted(tmp_path):
    # A layer is an overlay upperdir: a deleted base file is a 0:0 char device (whiteout).
    wh = tarfile.TarInfo("layer/gone")
    wh.type, wh.mode, wh.uid, wh.devmajor, wh.devminor = tarfile.CHRTYPE, 0o644, 0, 0, 0
    info = inspect_image_blob(_link_tar(tmp_path, [wh]))
    assert info.name == "app" and info.needs_root is True


@pytest.mark.tier1
def test_sudo_unpack_without_a_previous_layer(tmp_path, monkeypatch):
    blob = _raw_tar(tmp_path, [("layer", None, 0o755, 0), ("layer/f", b"", 0o644, 0)], gz=True)
    store = ImageStore(tmp_path / "dst")                                # nothing stored yet
    calls: list[list[str]] = []
    monkeypatch.setattr(blobmod.subprocess, "run", _fake_run_factory(calls))
    assert unpack_image_file(blob, store, sudo=True) == "app:1"
    image_dir = store.dir("app", "1")
    assert (image_dir / "layer" / "from-tar.txt").exists()
    assert store.get("app:1").parents == ()
    assert not list(image_dir.glob("layer.old-*"))
    assert not list(image_dir.glob("layer.incoming-*"))


@pytest.mark.tier1
def test_stale_incoming_dirs_are_swept_on_next_unpack(tmp_path, monkeypatch):
    blob = _raw_tar(tmp_path, [("layer", None, 0o755, 0), ("layer/f", b"", 0o644, 0)], gz=True)
    store = ImageStore(tmp_path / "dst")
    stale = store.dir("app", "1") / "layer.incoming-stale"
    (stale / "sub").mkdir(parents=True)                                 # a torn earlier extract
    (stale / "sub" / "half.bin").write_bytes(b"x")
    calls: list[list[str]] = []
    monkeypatch.setattr(blobmod.subprocess, "run", _fake_run_factory(calls))
    assert unpack_image_file(blob, store, sudo=True) == "app:1"
    assert not list(store.dir("app", "1").glob("layer.incoming-*"))
    assert (store.dir("app", "1") / "layer" / "from-tar.txt").exists()
    assert any(c[:2] == ["sudo", "rsync"] and c[-1].rstrip("/") == str(stale) for c in calls)


@pytest.mark.tier1
def test_failing_sudo_tar_leaves_no_incoming_and_reports_stderr(tmp_path, monkeypatch):
    blob = _raw_tar(tmp_path, [("layer", None, 0o755, 0), ("layer/f", b"", 0o644, 0)], gz=True)
    store = ImageStore(tmp_path / "dst")
    calls: list[list[str]] = []
    monkeypatch.setattr(blobmod.subprocess, "run", _fake_run_factory(calls, fail_tar=True))
    with pytest.raises(RuntimeError, match="No space left on device"):
        unpack_image_file(blob, store, sudo=True)
    image_dir = store.dir("app", "1")
    assert not list(image_dir.glob("layer.incoming-*"))                 # partial tree swept
    assert not list(image_dir.glob(".empty-*"))
    assert not (image_dir / "layer").exists() and not store.exists("app:1")
