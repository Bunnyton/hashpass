"""Tier1: a task's sources live on the pool as files; the archive is built on request."""
import io
import tarfile
import urllib.error
from http import HTTPStatus
from pathlib import Path

import pytest

from hashpass import cli
from hashpass.registry.sources import SourceStore


def _task(tmp_path: Path) -> Path:
    d = tmp_path / "lab"
    (d / "hp").mkdir(parents=True)
    (d / "Taskfile").write_text("stage\n", encoding="utf-8")
    (d / "hp" / "check").write_text("#!/bin/sh\n", encoding="utf-8")
    (d / "data").mkdir()
    return d


@pytest.mark.tier1
def test_archive_is_unpacked_into_files_and_listed(tmp_path):
    store = SourceStore(tmp_path / "src")
    store.put_archive("u/lab:1", cli.pack_task_source(_task(tmp_path)))
    assert store.listing("u/lab:1") == [
        {"path": "Taskfile", "size": 6, "dir": False},
        {"path": "data", "size": 0, "dir": True},
        {"path": "hp", "size": 0, "dir": True},
        {"path": "hp/check", "size": 10, "dir": False},
    ]
    assert store.read("u/lab:1", "hp/check") == b"#!/bin/sh\n"


@pytest.mark.tier1
def test_archive_on_request_holds_the_same_files(tmp_path):
    store = SourceStore(tmp_path / "src")
    store.put_archive("u/lab:1", cli.pack_task_source(_task(tmp_path)))
    out = tmp_path / "out"
    cli.unpack_task_source(store.archive("u/lab:1"), out)
    assert (out / "hp" / "check").read_text(encoding="utf-8") == "#!/bin/sh\n"


@pytest.mark.tier1
def test_a_new_push_replaces_the_tree(tmp_path):
    store = SourceStore(tmp_path / "src")
    d = _task(tmp_path)
    store.put_archive("u/lab:1", cli.pack_task_source(d))
    (d / "hp" / "check").unlink()
    store.put_archive("u/lab:1", cli.pack_task_source(d))
    assert "hp/check" not in [f["path"] for f in store.listing("u/lab:1")]


@pytest.mark.tier1
@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "hp/../../x"])
def test_reading_outside_the_tree_is_refused(tmp_path, bad):
    store = SourceStore(tmp_path / "src")
    store.put_archive("u/lab:1", cli.pack_task_source(_task(tmp_path)))
    with pytest.raises((ValueError, FileNotFoundError)):
        store.read("u/lab:1", bad)


@pytest.mark.tier1
def test_an_escaping_archive_is_refused_and_keeps_the_old_tree(tmp_path):
    store = SourceStore(tmp_path / "src")
    store.put_archive("u/lab:1", cli.pack_task_source(_task(tmp_path)))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(tarfile.TarError):
        store.put_archive("u/lab:1", buf.getvalue())
    assert store.read("u/lab:1", "Taskfile") == b"stage\n"


@pytest.mark.tier1
def test_missing_and_removed(tmp_path):
    store = SourceStore(tmp_path / "src")
    assert store.listing("u/lab:1") == []
    store.put_archive("u/lab:1", cli.pack_task_source(_task(tmp_path)))
    store.remove("u/lab:1")
    assert store.listing("u/lab:1") == []


@pytest.mark.tier2
def test_source_routes_store_files_and_serve_the_archive(registry, tmp_path):
    from hashpass.imagestore.store import ImageStore  # noqa: PLC0415
    from hashpass.registry.creds import CredentialCache  # noqa: PLC0415
    from hashpass.registry.remote import RemoteRegistry  # noqa: PLC0415
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "f").write_text("x", encoding="utf-8")
    ImageStore(registry.store.root).save("bob/lab", "1", seed, ())
    for user, role in (("bob", "author"), ("alice", "author"), ("kid", "student")):
        registry.users.add(user, "pw-correct", role=role)

    def client(user: str) -> RemoteRegistry:
        c = RemoteRegistry(registry.base_url, cache=CredentialCache(tmp_path / f"{user}.json"))
        c.login(user, "pw-correct")
        return c

    bob, alice, kid = client("bob"), client("alice"), client("kid")
    blob = cli.pack_task_source(_task(tmp_path))
    bob.push_source("bob/lab", "1", blob)
    paths = [f["path"] for f in alice.source_listing("bob/lab:1")]            # any author reads
    assert paths == ["Taskfile", "data", "hp", "hp/check"]
    assert alice.source_file("bob/lab:1", "hp/check") == b"#!/bin/sh\n"
    out = tmp_path / "out"
    cli.unpack_task_source(bob.source_archive("bob/lab:1"), out)
    assert (out / "Taskfile").is_file()
    with pytest.raises(urllib.error.HTTPError) as exc:                       # a student never
        kid.source_listing("bob/lab:1")
    assert exc.value.code == HTTPStatus.FORBIDDEN
    with pytest.raises(urllib.error.HTTPError) as exc:                       # write: own namespace
        alice.push_source("bob/lab", "1", blob)
    assert exc.value.code == HTTPStatus.FORBIDDEN
    with pytest.raises(urllib.error.HTTPError) as exc:
        alice.source_file("bob/lab:1", "../../../etc/passwd")
    assert exc.value.code == HTTPStatus.NOT_FOUND


@pytest.mark.tier2
def test_a_task_pushed_before_source_files_lists_its_attached_archive(registry, tmp_path):
    """Review 2026-10-14: the whole course on prod has only source.tar.gz attached -- show it."""
    from hashpass.imagestore.store import ImageStore  # noqa: PLC0415
    from hashpass.registry.creds import CredentialCache  # noqa: PLC0415
    from hashpass.registry.remote import RemoteRegistry  # noqa: PLC0415
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "f").write_text("x", encoding="utf-8")
    ImageStore(registry.store.root).save("bob/old", "1", seed, ())
    ImageStore(registry.store.root).save("bob/none", "1", seed, ())
    registry.users.add("bob", "pw-correct", role="author")
    bob = RemoteRegistry(registry.base_url, cache=CredentialCache(tmp_path / "bob.json"))
    bob.login("bob", "pw-correct")
    bob.push_attachment("bob/old", "1", "source.tar.gz", cli.pack_task_source(_task(tmp_path)))
    assert [f["path"] for f in bob.source_listing("bob/old:1")] == ["Taskfile", "data", "hp", "hp/check"]
    with pytest.raises(urllib.error.HTTPError) as exc:                       # nothing at all: 404
        bob.source_listing("bob/none:1")
    assert exc.value.code == HTTPStatus.NOT_FOUND
