from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore, StoredImage


@pytest.mark.tier1
@pytest.mark.parametrize("bad", ["../evil", "/etc/cron.d", "..", "", "a\x00b", ".", "a/../b"])
def test_save_rejects_unsafe_component(tmp_path, bad):
    # A traversing/absolute name or version must be refused BEFORE any write (§5 traversal guard):
    # an untrusted registry blob must never write outside the store. A NAME may be multi-segment,
    # but EVERY segment is checked, so a traversing segment (`a/../b`, `/etc/..`) is still refused.
    store = ImageStore(tmp_path / "images")
    src = _make_layer(tmp_path, "ok")
    with pytest.raises(ValueError, match="unsafe image"):
        store.save(bad, "1", src, ())
    with pytest.raises(ValueError, match="unsafe image"):
        store.save("ok", bad, src, ())


@pytest.mark.tier1
def test_namespaced_name_ok_but_slashed_version_rejected(tmp_path):
    # Namespacing: a multi-segment NAME (`ns/app`) is a valid nested path and round-trips,
    # but a VERSION must stay a single safe component ("/" in a version is refused).
    store = ImageStore(tmp_path / "images")
    src = _make_layer(tmp_path, "ok")
    store.save("ns/app", "1", src, ("base",))
    assert store.exists("ns/app:1")
    assert store.get("ns/app:1").parents == ("base",)
    assert store.list() == ["ns/app:1"]
    with pytest.raises(ValueError, match="unsafe image"):
        store.save("ok", "a/b", src, ())


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


@pytest.mark.tier1
def test_set_pool_digest_records_per_registry_and_write_meta_keeps_it(tmp_path):
    # One image may be pushed to / pulled from several pools (local registry, prod): the digest
    # each pool holds is remembered per registry; `pool_digest` stays the last one seen.
    store = ImageStore(tmp_path / "images")
    src = _make_layer(tmp_path, "b")
    ref = "bunnyton/debian:trixie"
    store.save("bunnyton/debian", "trixie", src, ())
    store.set_pool_digest(ref, "d1", registry="http://a:1")
    store.set_pool_digest(ref, "d2", registry="HTTP://B:2/")
    img = store.get(ref)
    assert img.pool_digest == "d2"
    assert img.pool_digests == {"a:1": "d1", "b:2": "d2"}
    store.write_meta("bunnyton/debian", "trixie", parents=())      # a pull's meta rewrite keeps them
    assert store.get(ref).pool_digests == {"a:1": "d1", "b:2": "d2"}
    store.save("bunnyton/debian", "trixie", src, ())               # a rebuild forgets them all
    assert store.get(ref).pool_digests == {} and store.get(ref).pool_digest is None


@pytest.mark.tier1
def test_alias_points_a_tag_at_a_pulled_revision(tmp_path):
    """`pull x:1` stores `x:1_v2` and points `x:1` at it, like `docker pull` tags the image."""
    store = ImageStore(tmp_path / "images")
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("rev", encoding="utf-8")
    store.save("bob/lab", "1_v2", src, ("bunnyton/debian:trixie_v1",))
    store.set_alias("bob/lab:1", "bob/lab:1_v2")
    assert store.exists("bob/lab:1")
    img = store.get("bob/lab:1")
    assert (img.version, img.parents) == ("1_v2", ("bunnyton/debian:trixie_v1",))
    assert store.list() == ["bob/lab:1_v2"]                     # an alias is not an image
    assert store.alias_of("bob/lab:1") == "bob/lab:1_v2"


@pytest.mark.tier1
def test_a_local_build_takes_the_tag_back_from_the_alias(tmp_path):
    store = ImageStore(tmp_path / "images")
    src = tmp_path / "src"
    src.mkdir()
    store.save("bob/lab", "1_v2", src, ())
    store.set_alias("bob/lab:1", "bob/lab:1_v2")
    store.save("bob/lab", "1", src, ())                          # hashengine build
    assert store.get("bob/lab:1").version == "1"
    assert store.alias_of("bob/lab:1") is None


@pytest.mark.tier1
def test_an_alias_to_a_missing_revision_is_ignored(tmp_path):
    store = ImageStore(tmp_path / "images")
    store.set_alias("bob/lab:1", "bob/lab:1_v9")
    assert not store.exists("bob/lab:1")


@pytest.mark.tier1
def test_a_pull_after_a_build_wins_the_tag(tmp_path):
    store = ImageStore(tmp_path / "images")
    src = tmp_path / "src"
    src.mkdir()
    store.save("bob/lab", "1", src, ())                          # the author's build
    store.save("bob/lab", "1_v2", src, ())
    store.set_alias("bob/lab:1", "bob/lab:1_v2")                 # then a pull
    assert store.get("bob/lab:1").version == "1_v2"
