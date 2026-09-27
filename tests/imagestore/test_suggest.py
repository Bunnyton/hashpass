"""Tier1: «быть может, вы искали …» -- the same short name published under another namespace."""
import pytest

from hashpass.imagestore.store import ImageStore, did_you_mean, similar_refs


@pytest.mark.tier1
def test_similar_refs_matches_short_name_under_other_namespaces_same_version_first():
    refs = ["alice/app:1", "bunnyton/debian:bookworm", "bunnyton/debian:trixie", "carol/debian:trixie"]
    assert similar_refs(refs, "debian:trixie") == [
        "bunnyton/debian:trixie", "carol/debian:trixie", "bunnyton/debian:bookworm"]


@pytest.mark.tier1
def test_similar_refs_excludes_the_exact_ref_and_unrelated_names():
    refs = ["bunnyton/debian:trixie", "alice/app:1"]
    assert similar_refs(refs, "bunnyton/debian:trixie") == []
    assert similar_refs(refs, "app:1") == ["alice/app:1"]
    assert similar_refs(refs, "ghost:1") == []


@pytest.mark.tier1
def test_similar_refs_bare_name_means_latest_and_caps_at_three():
    refs = [f"u{i}/tool:latest" for i in range(5)]
    assert similar_refs(refs, "tool") == ["u0/tool:latest", "u1/tool:latest", "u2/tool:latest"]


@pytest.mark.tier1
def test_did_you_mean_text():
    assert did_you_mean([]) == ""
    assert did_you_mean(["bunnyton/debian:trixie"]) == "быть может, вы искали bunnyton/debian:trixie?"
    assert did_you_mean(["a/x:1", "b/x:1"]) == "быть может, вы искали a/x:1 или b/x:1?"


@pytest.mark.tier1
def test_store_similar_walks_the_stored_refs(tmp_path):
    store = ImageStore(tmp_path / "images")
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("x", encoding="utf-8")
    store.save("bunnyton/debian", "trixie", src, ())
    assert store.similar("debian:trixie") == ["bunnyton/debian:trixie"]
    assert store.similar("bunnyton/debian:trixie") == []
