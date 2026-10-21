"""Tier1: tag a revision, remove one, fork a repository (spec 2026-10-21 §2.4, §2.7, §2.8)."""
from pathlib import Path

import pytest

from tests.registry.test_push_commit import _http, _Pool, _push_with_files


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Pool:
    p = _Pool(registry, tmp_path)
    p.push("bunnyton/debian", "trixie", image="base", user="bunnyton")
    return p


def _tag(pool: _Pool, src: str, to: str, user: str = "bob") -> tuple[int, dict]:
    name, _, tag = src.partition(":")
    return _http("POST", f"{pool.url}/revisions/{name}/{tag}/tag", token=pool.tok[user],
                 body={"from": src, "to": to})


@pytest.mark.tier1
def test_tag_shares_content_and_counts_on_its_own(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    _push_with_files(pool, b"image bob/lab:1", b"# readme")             # 1_v2 with files
    assert _tag(pool, "bob/lab:1_v2", "stable") == (201, {"ref": "bob/lab:stable_v1", "n": 1})
    store = pool.r.store
    assert store.get("bob/lab:stable_v1").digest == store.get("bob/lab:1_v2").digest
    assert store.blob_path("bob/lab:stable_v1").stat().st_ino == store.blob_path("bob/lab:1_v2").stat().st_ino
    root = store.root
    assert (root / "sources/bob/lab/stable_v1/README.md").read_text(encoding="utf-8") == "# readme"
    assert (root / "attachments/bob/lab/stable_v1/files/Taskfile").read_bytes() == b"image bob/lab:1"
    assert _tag(pool, "bob/lab:1", "stable")[1]["ref"] == "bob/lab:stable_v2"   # a tag -> its newest


@pytest.mark.tier1
def test_tag_refuses_reserved_and_foreign(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    assert _tag(pool, "bob/lab:1_v1", "x_v3")[0] == 400  # noqa: PLR2004
    assert _tag(pool, "bob/lab:1_v1", "stable", user="eve")[0] == 403  # noqa: PLR2004
    assert _tag(pool, "bob/lab:1_v9", "stable")[0] == 404  # noqa: PLR2004


@pytest.mark.tier1
def test_remove_a_revision_never_reuses_its_number(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    pool.push("bob/lab", "1", image="two")
    code, _ = _http("DELETE", f"{pool.url}/revisions/bob/lab/1/2", token=pool.tok["bob"])
    assert code == 200  # noqa: PLR2004
    assert not pool.r.store.exists("bob/lab:1_v2")
    assert pool.push("bob/lab", "1", image="three")[1]["ref"] == "bob/lab:1_v3"


@pytest.mark.tier1
def test_remove_a_parent_is_refused_with_its_dependents(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", parents=("bunnyton/debian:trixie",))
    code, body = _http("DELETE", f"{pool.url}/revisions/bunnyton/debian/trixie/1",
                       token=pool.tok["bunnyton"])
    assert code == 409  # noqa: PLR2004
    assert body["dependents"] == ["bob/lab:1_v1"]
    assert pool.r.store.exists("bunnyton/debian:trixie_v1")


@pytest.mark.tier1
def test_remove_by_another_user_is_403(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    assert _http("DELETE", f"{pool.url}/revisions/bob/lab/1/1", token=pool.tok["eve"])[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_fork_copies_a_revision_into_your_namespace(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", parents=("bunnyton/debian:trixie",))
    _push_with_files(pool, b"image bob/lab:1", b"# readme")
    code, body = _http("POST", f"{pool.url}/revisions/eve/lab/fork", token=pool.tok["eve"],
                       body={"from": "bob/lab:1_v2"})
    assert (code, body) == (201, {"ref": "eve/lab:1_v1", "n": 1})
    store = pool.r.store
    assert store.get("eve/lab:1_v1").digest == store.get("bob/lab:1_v2").digest
    assert store.get("eve/lab:1_v1").parents == ("bunnyton/debian:trixie_v1",)
    assert (store.root / "sources/eve/lab/1_v1/README.md").is_file()
    info = _http("GET", f"{pool.url}/revisions/eve/lab", token=pool.tok["eve"])[1]
    assert info["fork_of"] == "bob/lab:1_v2"
    assert [r["n"] for r in info["tags"]["1"]] == [1]


@pytest.mark.tier1
def test_fork_refuses_an_existing_repo_and_a_missing_source(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    pool.push("eve/lab", "1", image="mine", user="eve")
    assert _http("POST", f"{pool.url}/revisions/eve/lab/fork", token=pool.tok["eve"],
                 body={"from": "bob/lab:1_v1"})[0] == 409  # noqa: PLR2004
    assert _http("POST", f"{pool.url}/revisions/eve/other/fork", token=pool.tok["eve"],
                 body={"from": "bob/nothing:1"})[0] == 404  # noqa: PLR2004
    assert _http("POST", f"{pool.url}/revisions/bob/copy/fork", token=pool.tok["eve"],
                 body={"from": "bob/lab:1"})[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_revisions_listing(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    pool.push("bob/lab", "1", image="two")
    code, body = _http("GET", f"{pool.url}/revisions/bob/lab", token=pool.tok["eve"])
    assert code == 200  # noqa: PLR2004
    assert body["visibility"] == "public"
    assert [r["n"] for r in body["tags"]["1"]] == [1, 2]


@pytest.mark.tier1
def test_the_base_a_revision_was_built_on_cannot_be_removed(pool: _Pool) -> None:
    """Live check 2026-10-22: the base was deleted from under every task (it is not a `from`)."""
    sid = _http("POST", f"{pool.url}/revisions/bob/lab/1", token=pool.tok["bob"],
                body={"base": "bunnyton/debian:trixie"})[1]["staging"]
    pool.put("image", "bob/lab", "1", sid, pool.blob("bob/lab", "1", "one"))
    assert pool.commit("bob/lab", "1", sid)[1]["ref"] == "bob/lab:1_v1"
    assert pool.r.store.get("bob/lab:1_v1").base == "bunnyton/debian:trixie_v1"
    assert _tag(pool, "bob/lab:1_v1", "stable")[0] == 201  # noqa: PLR2004
    assert pool.r.store.get("bob/lab:stable_v1").base == "bunnyton/debian:trixie_v1"
    code, body = _http("DELETE", f"{pool.url}/revisions/bunnyton/debian/trixie/1",
                       token=pool.tok["bunnyton"])
    assert code == 409  # noqa: PLR2004
    assert body["dependents"] == ["bob/lab:1_v1", "bob/lab:stable_v1"]


@pytest.mark.tier1
def test_an_unknown_base_is_refused(pool: _Pool) -> None:
    sid = _http("POST", f"{pool.url}/revisions/bob/lab/1", token=pool.tok["bob"],
                body={"base": "bunnyton/nothere:1"})[1]["staging"]
    pool.put("image", "bob/lab", "1", sid, pool.blob("bob/lab", "1", "one"))
    code, body = pool.commit("bob/lab", "1", sid)
    assert code == 409  # noqa: PLR2004
    assert "bunnyton/nothere:1" in body["error"]
