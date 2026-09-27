"""Tier1: blob-only image records (server generations) and pool_digest bookkeeping (client)."""
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore


def _tmp_blob(tmp_path: Path, content: bytes = b"blob-bytes") -> Path:
    p = tmp_path / "incoming.tmp"
    p.write_bytes(content)
    return p


@pytest.mark.tier1
def test_publish_blob_creates_generation_and_lists_without_layer(tmp_path):
    store = ImageStore(tmp_path / "srv")
    digest = "ab12" * 16   # a well-formed sha256 hexdigest (64 hex chars)
    img = store.publish_blob("ns/app", "1", _tmp_blob(tmp_path), parents=("base:1",), digest=digest)
    assert img.digest == digest
    assert img.blob == f"blob-{digest}.tar.gz"
    assert (store.dir("ns/app", "1") / f"blob-{digest}.tar.gz").read_bytes() == b"blob-bytes"
    assert not (tmp_path / "incoming.tmp").exists()            # moved, not copied
    assert store.list() == ["ns/app:1"]                        # no layer/ dir needed
    assert store.exists("ns/app:1")
    assert store.get("ns/app:1").parents == ("base:1",)
    assert store.blob_path("ns/app:1") == store.dir("ns/app", "1") / f"blob-{digest}.tar.gz"


@pytest.mark.tier1
def test_publish_blob_replaces_generation_and_gcs_old_blob(tmp_path):
    store = ImageStore(tmp_path / "srv")
    d1, d2 = "d1" * 32, "d2" * 32   # well-formed sha256 hexdigests (64 hex chars)
    store.publish_blob("app", "1", _tmp_blob(tmp_path, b"one"), parents=(), digest=d1)
    store.publish_blob("app", "1", _tmp_blob(tmp_path, b"two"), parents=(), digest=d2)
    d = store.dir("app", "1")
    assert sorted(p.name for p in d.glob("blob-*.tar.gz")) == [f"blob-{d2}.tar.gz"]
    assert store.get("app:1").digest == d2
    assert store.blob_path("app:1").read_bytes() == b"two"


@pytest.mark.tier1
def test_legacy_layer_record_has_no_digest_and_no_blob(tmp_path):
    store = ImageStore(tmp_path / "local")
    layer = tmp_path / "layer"
    layer.mkdir()
    (layer / "f.txt").write_text("x", encoding="utf-8")
    store.save("app", "1", layer, ())
    img = store.get("app:1")
    assert img.digest is None and img.blob is None and img.pool_digest is None
    assert store.blob_path("app:1") is None
    assert store.list() == ["app:1"]


@pytest.mark.tier1
def test_set_pool_digest_and_write_meta_keep_each_other(tmp_path):
    store = ImageStore(tmp_path / "local")
    layer = tmp_path / "layer"
    layer.mkdir()
    store.save("app", "1", layer, ())
    store.set_pool_digest("app:1", "sha-1")
    assert store.get("app:1").pool_digest == "sha-1"
    store.write_meta("app", "1", parents=("base:1",))           # re-written meta keeps pool_digest
    got = store.get("app:1")
    assert got.parents == ("base:1",) and got.pool_digest == "sha-1"
    with pytest.raises(KeyError):
        store.set_pool_digest("ghost:1", "x")


@pytest.mark.tier1
def test_validate_ref_and_dir_reject_traversal(tmp_path):
    store = ImageStore(tmp_path / "s")
    with pytest.raises(ValueError, match="unsafe image"):
        ImageStore.validate_ref("../evil", "1")
    with pytest.raises(ValueError, match="unsafe image"):
        store.dir("ok", "../1")
    with pytest.raises(ValueError, match="unsafe image"):
        store.publish_blob("../evil", "1", _tmp_blob(tmp_path), parents=(), digest="d")


@pytest.mark.tier1
def test_publish_blob_rejects_a_malformed_digest(tmp_path):
    """
    Defense in depth: publish_blob refuses a malformed digest even from a trusted caller.

    The server always computes a real sha256 hexdigest, but a digest containing a
    path-traversal segment must never reach the filename it is built into.
    """
    store = ImageStore(tmp_path / "s")
    with pytest.raises(ValueError, match="unsafe image"):
        store.publish_blob("app", "1", _tmp_blob(tmp_path), parents=(), digest="../../etc/passwd")
