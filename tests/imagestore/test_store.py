from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore, StoredImage


@pytest.mark.tier1
@pytest.mark.parametrize("bad", ["../evil", "/etc/cron.d", "a/b", "..", "", "a\x00b", "."])
def test_save_rejects_unsafe_component(tmp_path, bad):
    # A traversing/absolute name or version must be refused BEFORE any write (§5 traversal guard):
    # an untrusted registry blob must never write outside the store.
    store = ImageStore(tmp_path / "images")
    src = _make_layer(tmp_path, "ok")
    with pytest.raises(ValueError, match="unsafe image"):
        store.save(bad, "1", src, ())
    with pytest.raises(ValueError, match="unsafe image"):
        store.save("ok", bad, src, ())


def _make_layer(tmp_path, name) -> Path:
    src = tmp_path / f"src-{name}"
    src.mkdir()
    (src / f"{name}.txt").write_text(name, encoding="utf-8")
    return src


@pytest.mark.tier1
def test_save_then_get_roundtrips(tmp_path):
    store = ImageStore(tmp_path / "images")
    src = _make_layer(tmp_path, "nettools")
    saved = store.save("nettools", "1", src, ("base",))
    assert isinstance(saved, StoredImage)

    got = store.get("nettools:1")
    assert got.name == "nettools"
    assert got.version == "1"
    assert got.parents == ("base",)
    assert (got.layer / "nettools.txt").read_text(encoding="utf-8") == "nettools"


@pytest.mark.tier1
def test_exists_true_and_false(tmp_path):
    store = ImageStore(tmp_path / "images")
    store.save("nettools", "1", _make_layer(tmp_path, "nettools"), ())
    assert store.exists("nettools:1")
    assert not store.exists("nettools:2")


@pytest.mark.tier1
def test_bare_ref_defaults_to_latest(tmp_path):
    store = ImageStore(tmp_path / "images")
    store.save("nettools", "latest", _make_layer(tmp_path, "nettools"), ())
    assert store.exists("nettools")
    assert store.get("nettools").version == "latest"


@pytest.mark.tier1
def test_get_missing_raises_keyerror(tmp_path):
    store = ImageStore(tmp_path / "images")
    with pytest.raises(KeyError):
        store.get("ghost:1")
