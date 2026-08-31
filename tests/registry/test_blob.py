import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image, unpack_image


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
