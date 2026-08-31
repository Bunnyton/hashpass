import pytest

from hashpass.imagestore.store import ImageStore


def _seed(store, tmp_path, name, version) -> None:
    src = tmp_path / f"src-{name}-{version}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, version, src, ())


@pytest.mark.tier1
def test_list_empty_store_is_empty(tmp_path):
    assert ImageStore(tmp_path / "images").list() == []


@pytest.mark.tier1
def test_list_returns_sorted_name_version(tmp_path):
    store = ImageStore(tmp_path / "images")
    _seed(store, tmp_path, "lab", "2")
    _seed(store, tmp_path, "base", "1")
    _seed(store, tmp_path, "lab", "1")
    assert store.list() == ["base:1", "lab:1", "lab:2"]
