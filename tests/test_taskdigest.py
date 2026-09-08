"""Tier1: task content digest — deterministic, sensitive to content and structure."""
import pytest

from hashpass.taskdigest import task_digest


def _make_task(root) -> None:
    (root / "bundle").mkdir(parents=True)
    (root / "bundle" / "checks.json").write_text('{"stages":[]}', encoding="utf-8")
    (root / "hp").mkdir()
    (root / "hp" / "grade").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (root / "task-meta.json").write_text('{"image_ref":"lab:1"}', encoding="utf-8")


@pytest.mark.tier1
def test_digest_deterministic_across_identical_trees(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    _make_task(a)
    b = tmp_path / "b"
    b.mkdir()
    _make_task(b)
    assert task_digest(a) == task_digest(b)


@pytest.mark.tier1
def test_digest_changes_on_content_edit(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    _make_task(a)
    before = task_digest(a)
    (a / "bundle" / "checks.json").write_text('{"stages":[1]}', encoding="utf-8")
    assert task_digest(a) != before


@pytest.mark.tier1
def test_digest_changes_on_added_file(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    _make_task(a)
    before = task_digest(a)
    (a / "hp" / "extra").write_text("x", encoding="utf-8")
    assert task_digest(a) != before
