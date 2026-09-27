import gzip
import io
import json
import stat
import tarfile
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
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
