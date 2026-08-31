"""Tier2 end-to-end: login -> auth push -> anonymous pull through the localhost server."""
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry


def _seed(store: ImageStore, tmp_path: Path, name: str, parents: tuple[str, ...],
          marker: str) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / f"{name}.txt").write_text(marker, encoding="utf-8")
    store.save(name, "1", src, parents)


@pytest.mark.tier2
def test_full_login_push_pull_roundtrip(registry, tmp_path):
    registry.users.add("dev", "s3cr3t")
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "base", (), "B")
    _seed(local, tmp_path, "tool", ("base:1",), "T")
    _seed(local, tmp_path, "lab", ("tool:1",), "L")

    cache = CredentialCache(tmp_path / "creds.json")
    client = RemoteRegistry(registry.base_url, cache=cache)
    client.login("dev", "s3cr3t")
    assert client.push(local, "lab:1") == ["base:1", "tool:1", "lab:1"]

    dest = ImageStore(tmp_path / "dest")
    pulled = RemoteRegistry(registry.base_url).pull("lab:1", dest)
    assert pulled == ["base:1", "tool:1", "lab:1"]
    assert (dest.get("lab:1").layer / "lab.txt").read_text(encoding="utf-8") == "L"
    assert dest.get("tool:1").parents == ("base:1",)
