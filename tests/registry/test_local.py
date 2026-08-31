from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.local import LocalRegistry


def _seed(store: ImageStore, tmp_path: Path, name: str, parents: tuple[str, ...],
          marker: str) -> str:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / f"{name}.txt").write_text(marker, encoding="utf-8")
    img = store.save(name, "1", src, parents)
    return f"{img.name}:{img.version}"


def _diamond(tmp_path: Path) -> ImageStore:
    store = ImageStore(tmp_path / "images")
    _seed(store, tmp_path, "base", (), "BASE")
    _seed(store, tmp_path, "a", ("base:1",), "A")
    _seed(store, tmp_path, "b", ("base:1",), "B")
    _seed(store, tmp_path, "child", ("a:1", "b:1"), "CHILD")
    return store


@pytest.mark.tier1
def test_push_moves_closure_bottom_up_and_is_idempotent(tmp_path):
    store = _diamond(tmp_path)
    reg = LocalRegistry(tmp_path / "registry")
    assert reg.push(store, "child:1") == ["base:1", "a:1", "b:1", "child:1"]
    assert reg.push(store, "child:1") == []  # idempotent no-op


@pytest.mark.tier1
def test_push_sibling_copies_only_new_refs(tmp_path):
    store = _diamond(tmp_path)
    _seed(store, tmp_path, "solo", ("base:1",), "SOLO")
    reg = LocalRegistry(tmp_path / "registry")
    reg.push(store, "child:1")
    assert reg.push(store, "solo:1") == ["solo:1"]  # base:1 already present


@pytest.mark.tier1
def test_local_push_ignores_token(tmp_path):
    store = _diamond(tmp_path)
    reg = LocalRegistry(tmp_path / "registry")
    sentinel = "ignored-by-local-registry"
    assert reg.push(store, "child:1", token=sentinel) == ["base:1", "a:1", "b:1", "child:1"]


@pytest.mark.tier1
def test_pull_moves_closure_with_content_and_parents(tmp_path):
    store = _diamond(tmp_path)
    reg = LocalRegistry(tmp_path / "registry")
    reg.push(store, "child:1")

    dest = ImageStore(tmp_path / "dest")
    assert reg.pull("child:1", dest) == ["base:1", "a:1", "b:1", "child:1"]
    assert reg.pull("child:1", dest) == []  # idempotent
    child = dest.get("child:1")
    assert child.parents == ("a:1", "b:1")
    assert (child.layer / "child.txt").read_text(encoding="utf-8") == "CHILD"
    assert (dest.get("base:1").layer / "base.txt").read_text(encoding="utf-8") == "BASE"


@pytest.mark.tier3
def test_push_root_owned_layer_uses_sudo(tmp_path):
    # Root-owned image layers (real build output) need sudo rsync inside ImageStore.save.
    # LocalRegistry(sudo=True) threads that through; requires scoped sudo (tier3, skipped
    # under `-m 'not tier3'`). A real tier3 run seeds a root-owned built layer here.
    store = ImageStore(tmp_path / "images")
    reg = LocalRegistry(tmp_path / "registry", sudo=True)
    ref = _seed(store, tmp_path, "rootimg", (), "ROOT")
    assert reg.push(store, ref) == [ref]
    dest = ImageStore(tmp_path / "dest")
    assert reg.pull(ref, dest) == [ref]
