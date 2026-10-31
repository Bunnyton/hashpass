"""Tier1: a whole fork offered back to its parent -- the request's life (spec 2026-10-31 §3.2)."""
from pathlib import Path

import pytest

from hashpass.registry import course_copies as cc
from hashpass.registry import course_merges as mg
from hashpass.registry import courses as c
from hashpass.registry.courses import CourseStore

DAY = 24 * 60 * 60


@pytest.fixture
def store(tmp_path: Path) -> CourseStore:
    return CourseStore(tmp_path / "courses")


def _pair(store: CourseStore) -> tuple[str, str]:
    parent = store.create("bob", "linux")
    with store.edit(parent.ref) as cur:
        b = c.add_block(cur, "Git")
        c.add_task(cur, "bob/a", "1", 1, b, by="bob")
        c.add_task(cur, "bob/draft", "1", 1, b, by="bob")["hidden"] = True
        cur.blocks[0]["open"] = False
    fork = store.create_copy(store.get(parent.ref), "kid", "f", "fork")
    with store.edit(fork.ref) as cur:
        c.add_task(cur, "kid/x", "1", 1, cur.blocks[0]["id"], by="kid")
        cur.blocks[0]["open"] = True
    return parent.ref, fork.ref


def _offer(store: CourseStore, parent: str, fork: str, now: float = 0.0) -> dict:
    with store.edit(parent) as cur:
        return mg.offer(cur, store.get(fork), by="kid", comment="возьмите", now=now)


@pytest.mark.tier1
def test_offer_requires_synced_fork(store: CourseStore) -> None:
    parent, fork = _pair(store)
    with store.edit(parent) as cur:
        c.add_block(cur, "Новое")
    with pytest.raises(ValueError, match="сначала подтяните изменения исходного курса"), store.edit(parent) as cur:
        mg.offer(cur, store.get(fork), by="kid", comment="", now=0.0)


@pytest.mark.tier1
def test_one_open_per_fork_refreshes(store: CourseStore) -> None:
    parent, fork = _pair(store)
    first = _offer(store, parent, fork)
    with store.edit(fork) as cur:
        c.add_task(cur, "kid/y", "1", 1, cur.blocks[0]["id"], by="kid")
    again = _offer(store, parent, fork, now=5.0)
    merges = store.get(parent).merges
    assert (len(merges), again["id"], merges[0]["at"]) == (1, first["id"], 5.0)
    assert [t["repo"] for t in merges[0]["snapshot"]["blocks"][0]["tasks"]] == ["bob/a", "kid/x", "kid/y"]


@pytest.mark.tier1
def test_accept_replaces_parent_structure_keeps_open_and_hidden(store: CourseStore) -> None:
    parent, fork = _pair(store)
    req = _offer(store, parent, fork)
    with store.edit(parent) as cur:
        done = mg.decide(cur, req["id"], accept=True, by="bob", now=1.0)
    assert (done["state"], done["decided_by"]) == ("merged", "bob")
    got = store.get(parent)
    block = got.blocks[0]
    assert block["open"] is False
    assert [(t["repo"], t["hidden"], t["added_by"]) for t in block["tasks"]] == [
        ("bob/a", False, "bob"), ("kid/x", False, "kid"), ("bob/draft", True, "bob")]


@pytest.mark.tier1
def test_stale_request_cannot_be_merged(store: CourseStore) -> None:
    parent, fork = _pair(store)
    req = _offer(store, parent, fork)
    with store.edit(parent) as cur:
        c.add_block(cur, "Новое")
    assert mg.stale(store.get(parent), store.get(parent).merges[0]) is True
    with pytest.raises(ValueError, match="запрос устарел"), store.edit(parent) as cur:
        mg.decide(cur, req["id"], accept=True, by="bob", now=1.0)
    with store.edit(parent) as cur:                     # rejecting one is fine
        assert mg.decide(cur, req["id"], accept=False, by="bob", now=1.0, reason="позже")["state"] == "rejected"


@pytest.mark.tier1
def test_rejected_hidden_after_7_days(store: CourseStore) -> None:
    parent, fork = _pair(store)
    req = _offer(store, parent, fork)
    with store.edit(parent) as cur:
        mg.decide(cur, req["id"], accept=False, by="bob", now=10.0, reason="нет")
    course = store.get(parent)
    assert [r["id"] for r in mg.shown(course, "kid", staff=False, now=10.0 + DAY)] == [req["id"]]
    assert mg.shown(course, "kid", staff=False, now=10.0 + 8 * DAY) == []
    assert mg.shown(course, "max", staff=False, now=11.0) == []
    assert len(mg.shown(course, "bob", staff=True, now=10.0 + 8 * DAY)) == 1


@pytest.mark.tier1
def test_withdraw_only_author(store: CourseStore) -> None:
    parent, fork = _pair(store)
    req = _offer(store, parent, fork)
    with pytest.raises(PermissionError), store.edit(parent) as cur:
        mg.withdraw(cur, req["id"], by="bob")
    with store.edit(parent) as cur:
        mg.withdraw(cur, req["id"], by="kid")
    assert store.get(parent).merges[0]["state"] == "withdrawn"


@pytest.mark.tier1
def test_changes_of_a_request(store: CourseStore) -> None:
    parent, fork = _pair(store)
    _offer(store, parent, fork)
    course = store.get(parent)
    assert [cc.describe(x) for x in mg.changes(course, course.merges[0])] == [
        "добавлено задание kid/x:1 в блок «Git»"]
