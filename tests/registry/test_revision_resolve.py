"""Tier1: revisions live in the pool's ImageStore as `<tag>_v<N>`; `tag`/`_latest`/`_vN` resolve to them."""
import hashlib
import os
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image_to_file
from hashpass.registry.passwords import UserStore
from hashpass.registry.server import PoolServer


def _publish(tmp_path: Path, pool: tuple[ImageStore, PoolServer], name: str, tag: str, text: str) -> str:
    """Publish one revision of name:tag (a blob + task/) the way a commit leaves it; return its ref."""
    srv, server = pool
    local = ImageStore(tmp_path / f"local-{text}")
    src = tmp_path / f"src-{text}"
    src.mkdir()
    (src / "f.txt").write_text(text, encoding="utf-8")
    local.save(name, tag, src, ())
    blob = tmp_path / f"{text}.blob"
    pack_image_to_file(local.get(f"{name}:{tag}"), blob)
    digest = hashlib.sha256(blob.read_bytes()).hexdigest()
    with server.repo(name).locked() as idx:
        n = idx.peek_next(tag)
        img = srv.publish_blob(name, f"{tag}_v{n}", blob, parents=(), digest=digest)
        task = img.layer.parent / "task"
        task.mkdir()
        (task / "task-meta.json").write_text(text, encoding="utf-8")
        idx.add(tag, {"image_digest": digest, "task_digest": text, "parents": [], "by": "bob"})
    return f"{name}:{tag}_v{n}"


@pytest.fixture
def pool(tmp_path: Path) -> tuple[ImageStore, PoolServer]:
    srv = ImageStore(tmp_path / "srv")
    return srv, PoolServer(store=srv, users=UserStore(tmp_path / "users.json"), secret=b"s" * 32)


@pytest.mark.tier1
def test_tag_latest_and_exact_revision_resolve(tmp_path: Path, pool: tuple[ImageStore, PoolServer]) -> None:
    _srv, server = pool
    v1 = _publish(tmp_path, pool, "bob/lab", "1", "one")
    v2 = _publish(tmp_path, pool, "bob/lab", "1", "two")
    assert (v1, v2) == ("bob/lab:1_v1", "bob/lab:1_v2")
    assert server.resolve("bob/lab", "1") == v2
    assert server.resolve("bob/lab", "1_latest") == v2
    assert server.resolve("bob/lab", "1_v1") == v1
    assert server.resolve("bob/lab", "1_v9") is None
    assert server.resolve("bob/lab", "2") is None


@pytest.mark.tier1
def test_unmigrated_version_resolves_to_itself(tmp_path: Path, pool: tuple[ImageStore, PoolServer]) -> None:
    srv, server = pool
    blob_src = tmp_path / "s"
    blob_src.mkdir()
    local = ImageStore(tmp_path / "l")
    local.save("bob/old", "1", blob_src, ())
    blob = tmp_path / "old.blob"
    pack_image_to_file(local.get("bob/old:1"), blob)
    srv.publish_blob("bob/old", "1", blob, parents=(), digest=hashlib.sha256(blob.read_bytes()).hexdigest())
    assert server.resolve("bob/old", "1") == "bob/old:1"


@pytest.mark.tier1
def test_link_revision_shares_the_blob(tmp_path: Path, pool: tuple[ImageStore, PoolServer]) -> None:
    srv, _server = pool
    v1 = _publish(tmp_path, pool, "bob/lab", "1", "one")
    img = srv.link_revision(v1, "bob/lab", "stable_v1", parents=("bunnyton/debian:trixie_v1",))
    src_blob, dst_blob = srv.blob_path(v1), srv.blob_path("bob/lab:stable_v1")
    assert dst_blob.stat().st_ino == src_blob.stat().st_ino
    assert img.digest == srv.get(v1).digest
    assert img.parents == ("bunnyton/debian:trixie_v1",)
    assert (img.layer.parent / "task" / "task-meta.json").read_text(encoding="utf-8") == "one"


@pytest.mark.tier1
def test_link_revision_copies_across_filesystems(tmp_path: Path, pool: tuple[ImageStore, PoolServer],
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    srv, _server = pool
    v1 = _publish(tmp_path, pool, "bob/lab", "1", "one")

    def cross_device(*_a: object, **_k: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", cross_device)
    img = srv.link_revision(v1, "bob/lab", "stable_v1", parents=())
    assert srv.blob_path("bob/lab:stable_v1").read_bytes() == srv.blob_path(v1).read_bytes()
    assert img.digest == srv.get(v1).digest


@pytest.mark.tier1
def test_hidden_dirs_are_not_images(tmp_path: Path, pool: tuple[ImageStore, PoolServer]) -> None:
    srv, _server = pool
    _publish(tmp_path, pool, "bob/lab", "1", "one")
    staged = ImageStore(srv.root / ".staging" / "abc")
    src = tmp_path / "st"
    src.mkdir()
    staged.save("bob/lab", "1", src, ())
    assert srv.list() == ["bob/lab:1_v1"]
