from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.refs import closure_refs, normalize_ref, split_ref


def _seed(store: ImageStore, tmp_path: Path, name: str, parents: tuple[str, ...]) -> str:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / f"{name}.txt").write_text(name, encoding="utf-8")
    img = store.save(name, "1", src, parents)
    return f"{img.name}:{img.version}"


@pytest.mark.tier1
def test_split_ref_bare_and_versioned():
    assert split_ref("base") == ("base", "latest")
    assert split_ref("base:1") == ("base", "1")
    assert split_ref("n:2:3") == ("n", "2:3")


@pytest.mark.tier1
def test_normalize_ref():
    assert normalize_ref("base") == "base:latest"
    assert normalize_ref("base:1") == "base:1"


@pytest.mark.tier1
def test_closure_single_image(tmp_path):
    store = ImageStore(tmp_path / "images")
    _seed(store, tmp_path, "solo", ())
    assert closure_refs("solo:1", store) == ["solo:1"]


@pytest.mark.tier1
def test_closure_linear_is_bottom_up(tmp_path):
    store = ImageStore(tmp_path / "images")
    _seed(store, tmp_path, "base", ())
    _seed(store, tmp_path, "app", ("base:1",))
    assert closure_refs("app:1", store) == ["base:1", "app:1"]


@pytest.mark.tier1
def test_closure_diamond_dedups_and_orders(tmp_path):
    store = ImageStore(tmp_path / "images")
    _seed(store, tmp_path, "base", ())
    _seed(store, tmp_path, "a", ("base:1",))
    _seed(store, tmp_path, "b", ("base:1",))
    _seed(store, tmp_path, "child", ("a:1", "b:1"))
    order = closure_refs("child:1", store)
    assert order == ["base:1", "a:1", "b:1", "child:1"]
    assert order.index("base:1") < order.index("a:1") < order.index("child:1")
    assert order.index("base:1") < order.index("b:1")


@pytest.mark.tier1
def test_closure_bare_ref_resolves_latest(tmp_path):
    store = ImageStore(tmp_path / "images")
    src = tmp_path / "src"
    src.mkdir()
    store.save("only", "latest", src, ())
    assert closure_refs("only", store) == ["only:latest"]
