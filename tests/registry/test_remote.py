"""Tier2: RemoteRegistry client against a localhost server (debi-owned fake layers)."""
import hashlib
import time
import urllib.error
from http import HTTPStatus
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry


def _seed(store: ImageStore, tmp_path: Path, name: str, parents: tuple[str, ...],
          marker: str) -> str:
    src = tmp_path / ("src-" + name.replace("/", "_"))
    src.mkdir(exist_ok=True)
    (src / "marker.txt").write_text(marker, encoding="utf-8")
    img = store.save(name, "1", src, parents)
    return f"{img.name}:{img.version}"


@pytest.mark.tier2
def test_login_caches_token(registry, tmp_path):
    registry.users.add("alice", "pw-correct", role="author")
    cache = CredentialCache(tmp_path / "creds.json")
    client = RemoteRegistry(registry.base_url, cache=cache)
    token = client.login("alice", "pw-correct")
    assert cache.cached_token(registry.base_url, now=time.time()) == token


@pytest.mark.tier2
def test_login_bad_password_raises_401(registry):
    registry.users.add("alice", "pw-correct", role="author")
    client = RemoteRegistry(registry.base_url)
    with pytest.raises(urllib.error.HTTPError) as exc:
        client.login("alice", "wrong")
    assert exc.value.code == HTTPStatus.UNAUTHORIZED


@pytest.mark.tier2
def test_push_requires_token(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "app", (), "APP")
    client = RemoteRegistry(registry.base_url)  # no cache, no login
    with pytest.raises(ValueError, match="requires a token"):
        client.push(local, "app:1")


@pytest.mark.tier2
def test_push_and_pull_closure_via_client(registry, tmp_path):
    registry.users.add("alice", "pw-correct", role="author")
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "base", (), "BASE")
    _seed(local, tmp_path, "app", ("base:1",), "APP")

    cache = CredentialCache(tmp_path / "creds.json")
    pusher = RemoteRegistry(registry.base_url, cache=cache)
    pusher.login("alice", "pw-correct")
    assert pusher.push(local, "app:1") == ["base:1", "app:1"]  # cached token reused
    assert pusher.push(local, "app:1") == []  # idempotent

    dest = ImageStore(tmp_path / "dest")
    anon = RemoteRegistry(registry.base_url)  # anonymous pull
    assert anon.pull("app:1", dest) == ["base:1", "app:1"]
    assert anon.pull("app:1", dest) == []  # idempotent
    assert (dest.get("app:1").layer / "marker.txt").read_text(encoding="utf-8") == "APP"
    assert dest.get("app:1").parents == ("base:1",)


@pytest.mark.tier2
def test_push_pull_namespaced_name(registry, tmp_path):
    # A namespaced ref (`alice/app:1`) survives the multi-segment URL path on push and pull.
    registry.users.add("alice", "pw-correct", role="author")
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "base", (), "BASE")
    _seed(local, tmp_path, "alice/app", ("base:1",), "APP")

    cache = CredentialCache(tmp_path / "creds.json")
    pusher = RemoteRegistry(registry.base_url, cache=cache)
    pusher.login("alice", "pw-correct")
    assert pusher.push(local, "alice/app:1") == ["base:1", "alice/app:1"]

    dest = ImageStore(tmp_path / "dest")
    assert RemoteRegistry(registry.base_url).pull("alice/app:1", dest) == ["base:1", "alice/app:1"]
    assert dest.list() == ["alice/app:1", "base:1"]


@pytest.mark.tier2
def test_forged_token_rejected_on_push(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "fresh", (), "F")
    client = RemoteRegistry(registry.base_url)
    forged = "forged.token.value"
    with pytest.raises(urllib.error.HTTPError) as exc:
        client.push(local, "fresh:1", token=forged)
    assert exc.value.code == HTTPStatus.UNAUTHORIZED


def _push_seeded(registry, tmp_path, name: str, marker: str) -> tuple[RemoteRegistry, str]:
    registry.users.add(f"u-{name}", "pw-correct", role="author")
    local = ImageStore(tmp_path / f"local-{name}-{marker}")
    src = tmp_path / f"src-{name}-{marker}"
    src.mkdir(exist_ok=True)
    (src / "marker.txt").write_text(marker, encoding="utf-8")
    local.save(name, "1", src, ())
    pusher = RemoteRegistry(registry.base_url, cache=CredentialCache(tmp_path / f"creds-{name}-{marker}.json"))
    pusher.login(f"u-{name}", "pw-correct")
    pusher.push(local, f"{name}:1", force=True)
    return pusher, f"{name}:1"


@pytest.mark.tier2
def test_pull_records_pool_digest_and_refresh_repulls_only_when_changed(registry, tmp_path):
    _pusher, ref = _push_seeded(registry, tmp_path, "app", "v1")
    anon = RemoteRegistry(registry.base_url)
    dest = ImageStore(tmp_path / "dest")
    assert anon.pull_many([ref], dest) == [ref]
    d1 = anon.image_digest(ref)
    assert d1 and dest.get(ref).pool_digest == d1
    assert (dest.get(ref).layer / "marker.txt").read_text(encoding="utf-8") == "v1"
    assert anon.pull_many([ref], dest, refresh=True) == []            # same digest -> nothing
    _push_seeded(registry, tmp_path, "app", "v2")                      # author re-pushes :1
    assert anon.pull_many([ref], dest) == []                          # legacy rule: present -> skip
    assert anon.pull_many([ref], dest, refresh=True) == [ref]         # digest changed -> re-pull
    assert (dest.get(ref).layer / "marker.txt").read_text(encoding="utf-8") == "v2"
    assert dest.get(ref).pool_digest == anon.image_digest(ref) != d1


@pytest.mark.tier2
def test_download_digest_mismatch_leaves_store_untouched(registry, tmp_path):
    _pusher, ref = _push_seeded(registry, tmp_path, "app", "v1")
    anon = RemoteRegistry(registry.base_url)
    dest = ImageStore(tmp_path / "dest")
    anon.pull_many([ref], dest)
    before = dest.get(ref)
    # Corrupt the served body: make the server's blob file differ from its published digest.
    registry.store.blob_path(ref).write_bytes(b"garbage")
    with pytest.raises(ValueError, match="digest mismatch"):
        anon.pull_many([ref], dest, refresh=True)
    assert dest.get(ref) == before                                    # meta untouched
    assert not list((dest.root / ".incoming").glob("*")) if (dest.root / ".incoming").exists() else True


@pytest.mark.tier2
def test_legacy_record_pulls_once_and_never_refreshes(registry, tmp_path):
    src = tmp_path / "src-old"
    src.mkdir()
    (src / "marker.txt").write_text("old", encoding="utf-8")
    registry.store.save("old", "1", src, ())                          # layer/-only, no digest
    anon = RemoteRegistry(registry.base_url)
    dest = ImageStore(tmp_path / "dest")
    assert anon.image_digest("old:1") is None and anon.has_image("old:1")
    assert anon.pull_many(["old:1"], dest, refresh=True) == ["old:1"]
    assert dest.get("old:1").pool_digest is None
    assert anon.pull_many(["old:1"], dest, refresh=True) == []       # no digest -> never stale


@pytest.mark.tier2
def test_push_streams_file_and_server_digest_matches_local_pack(registry, tmp_path):
    pusher, ref = _push_seeded(registry, tmp_path, "app", "v1")
    body = pusher._get_image(ref)                                     # noqa: SLF001
    assert hashlib.sha256(body).hexdigest() == pusher.image_digest(ref)
    assert body[:2] == b"\x1f\x8b"
