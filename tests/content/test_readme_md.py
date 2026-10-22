"""Tier1: every task has an README.md -- its description on the pool (user, 2026-10-14: «как на github»)."""
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
_MIN_LINES = 2   # a «# Title» and at least one line about the task
TASKS = sorted(p for p in CONTENT.iterdir() if (p / "Taskfile").is_file())


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=lambda p: p.name)
def test_task_has_a_readme(task: Path) -> None:
    about = task / "README.md"
    assert about.is_file(), f"{task.name}: нет README.md — описание задания на пуле"
    lines = [ln for ln in about.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines and lines[0].startswith("# "), f"{task.name}: README.md начинается с заголовка «# …»"
    assert len(lines) >= _MIN_LINES, f"{task.name}: README.md — заголовок и хотя бы строка о задании"
