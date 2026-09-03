"""Tier2: RemoteRegistry client against a localhost server (debi-owned fake layers)."""
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
    registry.users.add("alice", "pw-correct")
    cache = CredentialCache(tmp_path / "creds.json")
    client = RemoteRegistry(registry.base_url, cache=cache)
    token = client.login("alice", "pw-correct")
    assert cache.cached_token(registry.base_url, now=time.time()) == token


@pytest.mark.tier2
def test_login_bad_password_raises_401(registry):
    registry.users.add("alice", "pw-correct")
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
    registry.users.add("alice", "pw-correct")
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
    registry.users.add("alice", "pw-correct")
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
