"""Tier1: the block-grouped task catalog (auto-numbered, drag-reorderable)."""
import pytest

from hashpass.registry.catalog import Catalog


@pytest.mark.tier1
def test_add_task_auto_numbers_and_find(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    cat.add_task("a:1", "da", hidden=False)
    cat.add_task("b:1", "db", hidden=False)
    assert [(e.number, e.ref) for e in cat.entries()] == [(1, "a:1"), (2, "b:1")]
    assert cat.find("b:1").digest == "db"
    assert cat.find("zzz:1") is None
    assert cat.entries()[0].available is True   # the default block is open


@pytest.mark.tier1
def test_blocks_group_and_toggle(tmp_path):
    cat = Catalog(tmp_path / "c.json")
    b1 = cat.add_block("Основы")
    b2 = cat.add_block("Продвинутое")
    cat.add_task("a:1", "da", block_id=b1, hidden=False)
    cat.add_task("b:1", "db", block_id=b2, hidden=False)
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
    cat.add_task("a:1", "da", block_id=b1, hidden=False)
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


@pytest.mark.tier1
def test_republish_keeps_task_in_its_block_and_updates_digest(tmp_path):
    """`push --task` of a task already in the catalog must not move it to the last block."""
    cat = Catalog(tmp_path / "catalog.json")
    first = cat.add_block("Знакомство")
    cat.add_task("ns/a:1", "d1", block_id=first)
    cat.add_block("Архив")
    cat.set_task_hidden("ns/a:1", hidden=True)
    cat.add_task("ns/a:1", "d2")                      # re-push (no block given)
    entry = cat.find("ns/a:1")
    assert (entry.block_name, entry.digest, entry.hidden) == ("Знакомство", "d2", True)
    assert len(cat.entries()) == 1


@pytest.mark.tier1
def test_a_new_task_lands_hidden_in_the_named_block_and_a_republish_keeps_its_state(tmp_path):
    """Publish straight into a block, hidden by default; re-publishing keeps place and state."""
    cat = Catalog(tmp_path / "catalog.json")
    cat.add_task("ns/a:1", "d1", block_name="Знакомство")            # block created on the fly
    e = cat.find("ns/a:1")
    assert (e.block_name, e.hidden, e.available) == ("Знакомство", True, False)
    cat.set_task_hidden("ns/a:1", hidden=False)
    cat.add_task("ns/a:1", "d2", block_name="Знакомство")             # re-publish
    e = cat.find("ns/a:1")
    assert (e.digest, e.hidden) == ("d2", False)
    cat.add_task("ns/b:1", "d3", block_name="Знакомство")
    assert [x.ref for x in cat.blocks()[0].entries] == ["ns/a:1", "ns/b:1"]
    cat.add_task("ns/a:1", "d4", block_name="Поиск")                   # an explicit other block moves it
    assert cat.find("ns/a:1").block_name == "Поиск" and cat.find("ns/a:1").hidden is False


@pytest.mark.tier1
def test_move_task_steps_within_a_block_and_across_blocks(tmp_path):
    # User (2026-10-12): move tasks right inside hashpass. One step, like the web's ↑/↓: inside
    # a block it swaps with the neighbour; at the edge it crosses into the next block (empty
    # ones too); nothing else in the catalog changes.
    cat = Catalog(tmp_path / "c.json")
    a, _b, c = cat.add_block("A"), cat.add_block("B"), cat.add_block("C")
    for ref, blk in (("x:1", a), ("y:1", a), ("z:1", c)):
        cat.add_task(ref, "d", block_id=blk, hidden=False)
    cat.set_task_hidden("y:1", hidden=True)

    def layout() -> list[tuple[str, list[str]]]:
        return [(blk.name, [e.ref for e in blk.entries]) for blk in cat.blocks()]

    assert cat.move_task("y:1", -1) is True
    assert layout() == [("A", ["y:1", "x:1"]), ("B", []), ("C", ["z:1"])]
    assert cat.move_task("y:1", -1) is False                  # already the very first
    assert cat.move_task("x:1", 1) is True                    # last in A -> into empty B
    assert layout() == [("A", ["y:1"]), ("B", ["x:1"]), ("C", ["z:1"])]
    assert cat.move_task("z:1", -1) is True                   # first in C -> end of B
    assert layout() == [("A", ["y:1"]), ("B", ["x:1", "z:1"]), ("C", [])]
    assert cat.move_task("nope:1", 1) is False
    assert cat.find("y:1").hidden is True                     # state travels with the task
