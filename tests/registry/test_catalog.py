"""Tier1: the block-grouped task catalog (auto-numbered, drag-reorderable)."""
import pytest

from hashpass.registry.catalog import Catalog


@pytest.mark.tier1
def test_add_task_auto_numbers_and_find(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    cat.add_task("a:1", "da")
    cat.add_task("b:1", "db")
    assert [(e.number, e.ref) for e in cat.entries()] == [(1, "a:1"), (2, "b:1")]
    assert cat.find("b:1").digest == "db"
    assert cat.find("zzz:1") is None
    assert cat.entries()[0].available is True   # the default block is open


@pytest.mark.tier1
def test_blocks_group_and_toggle(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    b1 = cat.add_block("Основы")
    b2 = cat.add_block("Продвинутое")
    cat.add_task("a:1", "da", block_id=b1)
    cat.add_task("b:1", "db", block_id=b2)
    assert [(blk.name, [e.ref for e in blk.entries]) for blk in cat.blocks()] == \
           [("Основы", ["a:1"]), ("Продвинутое", ["b:1"])]
    assert [e.number for e in cat.entries()] == [1, 2]     # numbers run across blocks in order
    assert cat.set_block_open(b2, open_=False) is True
    assert {e.ref: e.available for e in cat.entries()} == {"a:1": True, "b:1": False}


@pytest.mark.tier1
def test_add_task_moves_between_blocks_and_remove(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    b1, b2 = cat.add_block("A"), cat.add_block("B")
    cat.add_task("x:1", "dx", block_id=b1)
    cat.add_task("x:1", "dx", block_id=b2)   # a ref lives in exactly one block -> moved to B
    assert [(blk.name, [e.ref for e in blk.entries]) for blk in cat.blocks()] == \
           [("A", []), ("B", ["x:1"])]
    assert cat.remove_task("x:1") is True
    assert cat.find("x:1") is None
    assert cat.remove_task("x:1") is False


@pytest.mark.tier1
def test_remove_block_only_when_empty(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    b1 = cat.add_block("A")
    cat.add_task("x:1", "dx", block_id=b1)
    assert cat.remove_block(b1) is False        # non-empty -> kept
    cat.remove_task("x:1")
    assert cat.remove_block(b1) is True


@pytest.mark.tier1
def test_set_layout_reorders_and_preserves_digests_and_names(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    b1 = cat.add_block("Первый")
    cat.add_task("a:1", "da", block_id=b1)
    cat.add_task("b:1", "db", block_id=b1)
    cat.set_layout([{"id": b1, "tasks": ["b:1", "a:1"]}])   # drag sends only id + refs
    blocks = cat.blocks()
    assert blocks[0].name == "Первый"                       # name preserved
    assert [e.ref for e in blocks[0].entries] == ["b:1", "a:1"]
    assert cat.find("a:1").digest == "da"                   # digests preserved


@pytest.mark.tier1
def test_migrates_legacy_flat_catalog(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"2": {"name": "b", "version": "1", "title": "T", "digest": "db"},'
                    ' "1": {"name": "a", "version": "1", "title": "T", "digest": "da"}}',
                    encoding="utf-8")
    cat = Catalog(path)
    assert [e.ref for e in cat.entries()] == ["a:1", "b:1"]   # one block, number order
    assert len(cat.blocks()) == 1
    assert cat.blocks()[0].open is True
