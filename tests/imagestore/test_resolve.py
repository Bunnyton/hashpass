import pytest

from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore, StoredImage


def _seed(store, tmp_path, name, parents) -> StoredImage:
    src = tmp_path / f"src-{name}"
    src.mkdir()
    (src / f"{name}.txt").write_text(name, encoding="utf-8")
    return store.save(name, "1", src, parents)


@pytest.mark.tier1
def test_linear_chain_topmost_first(tmp_path):
    store = ImageStore(tmp_path / "images")
    a = _seed(store, tmp_path, "a", ())
    b = _seed(store, tmp_path, "b", ("a:1",))
    c = _seed(store, tmp_path, "c", ("b:1",))
    assert resolve_lowers(("c:1",), store) == [c.layer, b.layer, a.layer]


@pytest.mark.tier1
def test_diamond_dedups_shared_ancestor_at_bottom(tmp_path):
    store = ImageStore(tmp_path / "images")
    a = _seed(store, tmp_path, "a", ())
    b = _seed(store, tmp_path, "b", ("a:1",))
    c = _seed(store, tmp_path, "c", ("a:1",))
    _seed(store, tmp_path, "d", ("b:1", "c:1"))

    lowers = resolve_lowers(("b:1", "c:1"), store)
    # rightmost `from` (c) is highest priority => topmost; shared ancestor a
    # appears exactly once, at the bottom; result is fully deterministic.
    assert lowers == [c.layer, b.layer, a.layer]
    assert lowers[-1] == a.layer


@pytest.mark.tier1
def test_empty_parents_returns_empty(tmp_path):
    store = ImageStore(tmp_path / "images")
    assert resolve_lowers((), store) == []
