"""Tier1: a task's wiki keeps its own versions on the side; a save never overwrites a newer page."""
import io
import tarfile
from pathlib import Path

import pytest

from hashpass.registry import wiki_store
from hashpass.registry.wiki_store import (
    WikiConflict,
    WikiRejected,
    WikiStore,
    pack,
    parse_tags,
    unpack,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def _store(tmp_path: Path) -> WikiStore:
    return WikiStore(tmp_path, "bob/regex")


@pytest.mark.tier1
def test_first_save_makes_version_one(tmp_path: Path) -> None:
    s = _store(tmp_path)
    assert s.head() == 0 and not s.exists() and s.files() == {}
    assert s.save(0, {"wiki.md": b"# Hi\n"}, by="bob", message="first") == 1
    assert s.files() == {"wiki.md": b"# Hi\n"} and s.exists()
    v = s.versions()[0]
    assert (v["n"], v["by"], v["message"], v["changed"]) == (1, "bob", "first", ["wiki.md"])
    assert v["at"]


@pytest.mark.tier1
def test_different_pages_from_the_same_base_both_pass(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"# Hi\n"}, by="bob")
    assert s.save(1, {"wiki/a.md": b"a"}, by="bob") == 2  # noqa: PLR2004
    assert s.save(1, {"wiki/b.md": b"b"}, by="eve") == 3  # noqa: PLR2004
    assert s.files() == {"wiki.md": b"# Hi\n", "wiki/a.md": b"a", "wiki/b.md": b"b"}


@pytest.mark.tier1
def test_the_same_page_from_a_stale_base_conflicts(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"1"}, by="bob")
    s.save(1, {"wiki.md": b"2"}, by="eve")
    with pytest.raises(WikiConflict) as err:
        s.save(1, {"wiki.md": b"3"}, by="bob")
    assert err.value.paths == ["wiki.md"]
    assert s.head() == 2 and s.files()["wiki.md"] == b"2"  # noqa: PLR2004


@pytest.mark.tier1
def test_a_never_cloned_folder_conflicts_once_the_pool_has_a_wiki(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"pool"}, by="eve")
    with pytest.raises(WikiConflict):
        s.save(0, s.local_changes(0, {"wiki.md": b"mine"}), by="bob")


@pytest.mark.tier1
def test_no_changes_make_no_version(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"x"}, by="bob")
    assert s.save(1, {"wiki.md": b"x"}, by="bob") == 1
    assert s.save(1, s.local_changes(1, {"wiki.md": b"x"}), by="bob") == 1
    assert len(s.versions()) == 1


@pytest.mark.tier1
def test_a_page_is_deleted_with_none(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"x", "wiki/a.md": b"a"}, by="bob")
    s.save(1, {"wiki/a.md": None}, by="bob")
    assert s.files() == {"wiki.md": b"x"}
    assert s.files(1) == {"wiki.md": b"x", "wiki/a.md": b"a"}       # the old version stays
    assert s.local_changes(1, {"wiki.md": b"x"}) == {"wiki/a.md": None}


@pytest.mark.tier1
def test_rebase_brings_upstream_pages_and_keeps_local_ones(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"x", "wiki/a.md": b"a"}, by="bob")
    s.save(1, {"wiki/a.md": b"a2"}, by="eve")
    head, merged = s.rebase(1, {"wiki.md": b"x", "wiki/a.md": b"a", "wiki/b.md": b"b"})
    assert head == 2 and merged == {"wiki.md": b"x", "wiki/a.md": b"a2", "wiki/b.md": b"b"}  # noqa: PLR2004
    assert s.head() == 2                                                # rebase writes nothing  # noqa: PLR2004
    with pytest.raises(WikiConflict):
        s.rebase(1, {"wiki.md": b"x", "wiki/a.md": b"mine"})


@pytest.mark.tier1
@pytest.mark.parametrize("path", ["../x.md", "/wiki.md", "wiki/.h.md", "notes.md", "wiki/x.txt",
                                  "wiki/../wiki.md", "wiki/a b.md", "wiki", "wiki/"])
def test_paths_outside_the_wiki_are_rejected(path: str) -> None:
    with pytest.raises(WikiRejected):
        wiki_store.check_path(path)


@pytest.mark.tier1
def test_only_real_raster_images_pass() -> None:
    assert wiki_store.check_file("wiki/p.png", PNG) == "image/png"
    assert wiki_store.check_file("wiki/p.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 8) == "image/jpeg"
    assert wiki_store.check_file("wiki/p.gif", b"GIF89a" + b"\0" * 8) == "image/gif"
    assert wiki_store.check_file("wiki/p.webp", b"RIFF\0\0\0\0WEBP" + b"\0" * 8) == "image/webp"
    assert wiki_store.check_file("wiki/a.md", "# Тема\n".encode()) == "text/markdown; charset=utf-8"
    for path, data in (("wiki/p.png", b"<svg onload=alert(1)>"), ("wiki/p.svg", b"<svg/>"),
                       ("wiki/a.md", b"\xff\xfe bad utf8"), ("wiki/p.jpg", PNG)):
        with pytest.raises(WikiRejected):
            wiki_store.check_file(path, data)


@pytest.mark.tier1
def test_sizes_are_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(WikiRejected):
        wiki_store.check_file("wiki/p.png", PNG + b"\0" * wiki_store.MAX_FILE)
    monkeypatch.setattr(wiki_store, "MAX_TOTAL", 100)
    s = _store(tmp_path)
    with pytest.raises(WikiRejected):
        s.save(0, {"wiki.md": b"x" * 60, "wiki/a.md": b"y" * 60}, by="bob")
    assert s.head() == 0


@pytest.mark.tier1
def test_unchanged_files_are_hard_links_to_the_old_version(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"x", "wiki/p.png": PNG}, by="bob")
    s.save(1, {"wiki.md": b"y"}, by="bob")
    base = tmp_path / "bob" / "regex" / "wiki"
    assert (base / "v1" / "wiki" / "p.png").stat().st_ino == (base / "v2" / "wiki" / "p.png").stat().st_ino


@pytest.mark.tier1
def test_diff_shows_what_a_version_changed(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"a\n"}, by="bob")
    s.save(1, {"wiki.md": b"b\n", "wiki/n.md": b"new\n"}, by="bob")
    rows = {r["path"]: r for r in s.diff(1, 2)}
    assert rows["wiki.md"]["change"] == "changed" and "+b" in rows["wiki.md"]["diff"]
    assert rows["wiki/n.md"]["change"] == "added"


@pytest.mark.tier1
def test_a_fork_copies_the_history_and_drop_removes_it(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"a"}, by="bob")
    s.save(1, {"wiki.md": b"b"}, by="bob")
    fork = WikiStore(tmp_path, "eve/regex")
    s.copy_to(fork)
    assert fork.head() == 2 and fork.files(1) == {"wiki.md": b"a"}  # noqa: PLR2004
    s.drop()
    assert s.head() == 0 and fork.head() == 2  # noqa: PLR2004


@pytest.mark.tier1
def test_the_repo_name_is_checked(tmp_path: Path) -> None:
    for bad in ("../x", "bob", "bob/../../x", "bob/a/b"):
        with pytest.raises(ValueError, match="имя"):
            WikiStore(tmp_path, bad)


@pytest.mark.tier1
def test_tags_live_in_a_block_at_the_top_of_wiki_md() -> None:
    assert parse_tags("---\ntags: Regex, #grep\n---\n# T\n") == (["regex", "grep"], "# T\n")
    assert parse_tags("---\ntags: [a, b]\n---\nbody") == (["a", "b"], "body")
    assert parse_tags("# no tags\n") == ([], "# no tags\n")


@pytest.mark.tier1
def test_pack_unpack_round_trip_and_an_escaping_member_is_refused() -> None:
    files = {"wiki.md": b"# x\n", "wiki/p.png": PNG}
    assert unpack(pack(files)) == files
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil.md")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(WikiRejected):
        unpack(buf.getvalue())


@pytest.mark.tier1
def test_a_page_equal_to_the_pool_one_is_no_conflict(tmp_path: Path) -> None:
    # a folder that never kept its version (or lost the marker) but holds exactly the pool's pages
    s = _store(tmp_path)
    s.save(0, {"wiki.md": b"same"}, by="bob")
    assert s.rebase(0, {"wiki.md": b"same"}) == (1, {"wiki.md": b"same"})
    assert s.save(0, s.local_changes(0, {"wiki.md": b"same", "wiki/n.md": b"n"}), by="bob") == 2  # noqa: PLR2004
    with pytest.raises(WikiConflict):
        s.save(0, s.local_changes(0, {"wiki.md": b"other"}), by="bob")
