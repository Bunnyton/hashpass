"""Tier1: `observe` names files by absolute path -- a relative one is read from / and never matches."""
from pathlib import Path

import pytest

from tests.content.recipes import is_task_dir, parse_task

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TASKS = sorted(p for p in CONTENT.iterdir() if is_task_dir(p))


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=lambda p: p.name)
def test_observe_paths_are_absolute(task: Path) -> None:
    # first-steps (2026-10-13 regression run): `observe hello.txt` was checked as /hello.txt, so the
    # student's ~/hello.txt never passed.
    recipe = parse_task(task)
    rel = [p for s in recipe.stages for p in (*s.observe, *s.observe_bool)
           if p != "output" and not p.removeprefix("perms:").startswith("/")]
    assert not rel, f"{task.name}: observe needs absolute paths: {rel}"
