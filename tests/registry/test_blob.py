import io
import json
import tarfile

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image, unpack_image


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
