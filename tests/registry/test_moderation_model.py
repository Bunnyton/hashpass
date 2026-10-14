"""Tier1: task moderation in the catalog -- pending / approved / rejected (spec 2026-10-14)."""
import json

import pytest

from hashpass.registry.catalog import REJECT_TTL, Catalog
from hashpass.registry.passwords import UserStore
from hashpass.registry.pool_settings import PoolSettings


def _cat(tmp_path) -> Catalog:
    return Catalog(tmp_path / "catalog.json")


@pytest.mark.tier1
def test_a_new_task_waits_for_approval_and_students_do_not_see_it(tmp_path):
    cat = _cat(tmp_path)
    cat.add_task("bob/lab:1", "d1", block_name="Б", hidden=False)
    e = cat.find("bob/lab:1")
    assert (e.state, e.approved_digest, e.available) == ("pending", "", False)
    assert cat.approve("bob/lab:1") == "d1"
    e = cat.find("bob/lab:1")
    assert (e.state, e.approved_digest, e.available) == ("approved", "d1", True)


@pytest.mark.tier1
def test_auto_approval_publishes_straight_away(tmp_path):
    cat = _cat(tmp_path)
    cat.add_task("bob/lab:1", "d1", hidden=False, auto=True)
    e = cat.find("bob/lab:1")
    assert (e.state, e.approved_digest, e.available) == ("approved", "d1", True)


@pytest.mark.tier1
def test_an_update_waits_again_while_students_keep_the_approved_version(tmp_path):
    cat = _cat(tmp_path)
    cat.add_task("bob/lab:1", "d1", hidden=False)
    cat.approve("bob/lab:1")
    cat.add_task("bob/lab:1", "d2")
    e = cat.find("bob/lab:1")
    assert (e.state, e.digest, e.approved_digest, e.available) == ("pending", "d2", "d1", True)
    assert e.as_dict()["pending_update"] is True


@pytest.mark.tier1
def test_reject_keeps_a_reason_and_a_new_push_resubmits(tmp_path):
    cat = _cat(tmp_path)
    cat.add_task("bob/lab:1", "d1", hidden=False)
    assert cat.reject("bob/lab:1", "нет финала", now=1000.0) is True
    e = cat.find("bob/lab:1")
    assert (e.state, e.reason, e.rejected_at, e.available) == ("rejected", "нет финала", 1000.0, False)
    assert e.as_dict()["expires_at"] == 1000.0 + REJECT_TTL
    cat.add_task("bob/lab:1", "d2")
    e = cat.find("bob/lab:1")
    assert (e.state, e.reason, e.rejected_at) == ("pending", "", 0.0)
    assert cat.reject("ghost:1", "", now=1.0) is False
    assert cat.approve("ghost:1") is None


@pytest.mark.tier1
def test_purge_drops_only_rejected_tasks_older_than_a_week(tmp_path):
    cat = _cat(tmp_path)
    for ref in ("a/old:1", "a/fresh:1", "a/back:1", "a/ok:1"):
        cat.add_task(ref, "d", hidden=False)
    cat.reject("a/old:1", "", now=0.0)
    cat.reject("a/fresh:1", "", now=REJECT_TTL)
    cat.reject("a/back:1", "", now=0.0)
    cat.add_task("a/back:1", "d2")                     # re-pushed the same day: not rejected now
    assert cat.purge_rejected(REJECT_TTL + 1) == ["a/old:1"]
    assert {e.ref for e in cat.entries()} == {"a/fresh:1", "a/back:1", "a/ok:1"}


@pytest.mark.tier1
def test_a_legacy_catalog_reads_as_approved(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"blocks": [{"id": "b", "name": "Б", "open": True, "tasks": [
        {"name": "bunnyton/cd-abs", "version": "1", "digest": "d1", "hidden": False}]}]}),
        encoding="utf-8")
    e = Catalog(path).find("bunnyton/cd-abs:1")
    assert (e.state, e.approved_digest, e.available) == ("approved", "d1", True)


@pytest.mark.tier1
def test_layout_keeps_the_moderation_state(tmp_path):
    cat = _cat(tmp_path)
    cat.add_task("bob/lab:1", "d1", block_name="Б", hidden=False)
    cat.approve("bob/lab:1")
    cat.add_task("bob/lab:1", "d2")
    cat.add_task("bob/no:1", "x", block_name="Б")
    cat.reject("bob/no:1", "почему", now=5.0)
    block = cat.blocks()[0]
    cat.set_layout([{"id": block.id, "name": "Новое имя", "open": True,
                     "tasks": ["bob/no:1", "bob/lab:1"]}])
    lab, no = cat.find("bob/lab:1"), cat.find("bob/no:1")
    assert (lab.state, lab.approved_digest, lab.digest) == ("pending", "d1", "d2")
    assert (no.state, no.reason, no.rejected_at) == ("rejected", "почему", 5.0)


@pytest.mark.tier1
def test_auto_approve_flags_default_off_even_for_the_admin(tmp_path):
    pool = PoolSettings(tmp_path / "pool-settings.json")
    assert pool.auto_approve is False
    pool.set_auto_approve(on=True)
    assert PoolSettings(tmp_path / "pool-settings.json").auto_approve is True
    users = UserStore(tmp_path / "users.json")
    users.add("root", "pw-correct1", role="admin")
    assert users.auto_approve("root") is False
    users.set_auto_approve("root", on=True)
    assert users.auto_approve("root") is True
    assert users.auto_approve("ghost") is False
