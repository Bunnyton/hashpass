"""Tier1: the ordered task catalog."""
import pytest

from hashpass.registry.catalog import Catalog, CatalogEntry


@pytest.mark.tier1
def test_put_get_find_ordered_by_number(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    cat.put(CatalogEntry(2, "b", "1", "Second", "d2"))
    cat.put(CatalogEntry(1, "a", "1", "First", "d1"))
    assert [e.number for e in cat.entries()] == [1, 2]
    assert cat.get(1).name == "a"
    assert cat.get(9) is None
    assert cat.find("b:1").ref == "b:1"
    assert cat.find("zzz:1") is None


@pytest.mark.tier1
def test_put_overwrites_slot(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    cat.put(CatalogEntry(1, "a", "1", "A", "d1"))
    cat.put(CatalogEntry(1, "b", "2", "B", "d2"))
    assert len(cat.entries()) == 1
    e = cat.get(1)
    assert (e.name, e.version, e.title, e.digest) == ("b", "2", "B", "d2")


@pytest.mark.tier1
def test_entry_ref_and_as_dict():
    number = 3
    e = CatalogEntry(number, "ns/app", "2", "T", "abc")
    assert e.ref == "ns/app:2"
    d = e.as_dict()
    assert d["number"] == number
    assert d["ref"] == "ns/app:2"
    assert d["digest"] == "abc"
    assert d["available"] is True   # tasks default to available


@pytest.mark.tier1
def test_remove_and_availability(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    cat.put(CatalogEntry(1, "a", "1", "A", "d1"))
    assert cat.get(1).available is True
    assert cat.set_available(1, available=False) is True
    assert cat.get(1).available is False
    assert cat.set_available(99, available=False) is False   # no such slot
    # availability persists across reload and survives a re-read of entries()
    assert Catalog(tmp_path / "c.json").entries()[0].available is False
    assert cat.remove(1) is True
    assert cat.get(1) is None
    assert cat.remove(1) is False


@pytest.mark.tier1
def test_available_roundtrip_through_put(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    cat.put(CatalogEntry(1, "a", "1", "A", "d1", available=False))
    assert cat.get(1).available is False
    assert cat.get(1).as_dict()["available"] is False
