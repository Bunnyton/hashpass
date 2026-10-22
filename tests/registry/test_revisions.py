"""Tier1: a repository's index of immutable, numbered revisions per tag (spec 2026-10-21 §2)."""
import threading
from pathlib import Path

import pytest

from hashpass.registry.revisions import RepoIndex, check_tag, parse_version, revision_version


def _rev(digest: str = "a") -> dict:
    return {"image_digest": digest * 64, "task_digest": "", "parents": [], "by": "bob"}


@pytest.mark.tier1
@pytest.mark.parametrize("tag", ["1_v2", "x_latest", "stable_v10", "_latest"])
def test_check_tag_rejects_reserved(tag: str) -> None:
    with pytest.raises(ValueError, match="зарезервирован"):
        check_tag(tag)


@pytest.mark.tier1
@pytest.mark.parametrize("tag", ["1", "v2", "stable", "1_vx", "1_v", "latest", "1-v2"])
def test_check_tag_accepts_ordinary(tag: str) -> None:
    check_tag(tag)


@pytest.mark.tier1
def test_parse_and_build_version() -> None:
    assert parse_version("1_v3") == ("1", 3, False)
    assert parse_version("1_latest") == ("1", None, True)
    assert parse_version("1") == ("1", None, False)
    assert parse_version("stable_v12") == ("stable", 12, False)
    assert revision_version("1", 3) == "1_v3"


@pytest.mark.tier1
def test_meta_defaults(tmp_path: Path) -> None:
    idx = RepoIndex(tmp_path, "bob/lab")
    assert (idx.visibility, idx.hide_sources, idx.fork_of) == ("public", False, "")
    assert idx.tags() == []
    assert idx.latest("1") is None


@pytest.mark.tier1
def test_numbers_are_monotonic_and_never_reused(tmp_path: Path) -> None:
    idx = RepoIndex(tmp_path, "bob/lab")
    with idx.locked() as w:
        numbers = [w.add("1", _rev("a")).n, w.add("1", _rev("b")).n]
        w.remove("1", numbers[-1])
        numbers.append(w.add("1", _rev("c")).n)
        other = w.add("2", _rev("d")).n              # every tag counts on its own
    assert numbers == [1, 2, 3]
    assert other == 1
    assert [r.n for r in idx.revisions("1")] == [1, 3]
    assert idx.latest("1").image_digest == "c" * 64
    assert idx.get("1", 2) is None


@pytest.mark.tier1
def test_add_outside_lock_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        RepoIndex(tmp_path, "bob/lab").add("1", _rev())


@pytest.mark.tier1
def test_parallel_adds_get_distinct_numbers(tmp_path: Path) -> None:
    got: list[int] = []
    lock = threading.Lock()

    def push() -> None:
        with RepoIndex(tmp_path, "bob/lab").locked() as w:
            n = w.add("1", _rev()).n
        with lock:
            got.append(n)

    threads = [threading.Thread(target=push) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == list(range(1, 9))


@pytest.mark.tier1
def test_roundtrip_reload(tmp_path: Path) -> None:
    with RepoIndex(tmp_path, "bob/lab").locked() as w:
        w.add("1", _rev() | {"parents": ["bunnyton/debian:trixie_v1"], "merged_from": "eve/lab:1_v2"})
        w.set_meta(visibility="private", hide_sources=True, fork_of="eve/lab:1_v2")
    again = RepoIndex(tmp_path, "bob/lab")
    rev = again.latest("1")
    assert rev.parents == ("bunnyton/debian:trixie_v1",)
    assert rev.merged_from == "eve/lab:1_v2"
    assert rev.at                                           # timestamped on add
    assert (again.visibility, again.hide_sources, again.fork_of) == ("private", True, "eve/lab:1_v2")


@pytest.mark.tier1
def test_set_meta_rejects_unknown_visibility(tmp_path: Path) -> None:
    with RepoIndex(tmp_path, "bob/lab").locked() as w, pytest.raises(ValueError, match="видимость"):
        w.set_meta(visibility="secret")


@pytest.mark.tier1
def test_peek_next_names_the_next_add(tmp_path: Path) -> None:
    with RepoIndex(tmp_path, "bob/lab").locked() as w:
        first = w.peek_next("1")
        assert w.add("1", _rev()).n == first
        w.remove("1", first)
        assert w.peek_next("1") == first + 1


@pytest.mark.tier1
def test_people_see_a_version_beside_the_tag() -> None:
    from hashpass.registry.revisions import human_ref  # noqa: PLC0415
    assert human_ref("bob/lab:1_v3") == "bob/lab:1, версия 3"
    assert human_ref("bob/lab:stable") == "bob/lab:stable"
