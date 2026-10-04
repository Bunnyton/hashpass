"""Tier1: a task's goal is said once -- by its `stage` line -- not again in the brief."""
import re
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TASKS = sorted(p for p in CONTENT.iterdir() if (p / "Taskfile").is_file())
# User (2026-10-04): brief «## Задание: Спроси у системы, кто ты. Нажми Enter.» + stage
# «Узнай у системы, под каким именем…» + on enter = the same task three times; «оставить только
# “Спроси у системы, кто ты?”». The last page of a brief does not wait for Enter either.
_TASK_SECTION = re.compile(r"^#+\s*Задани[ея]\b", re.MULTILINE | re.IGNORECASE)
_PRESS_ENTER = re.compile(r"Нажми\s+\**Enter", re.IGNORECASE)


def _briefs(task: Path) -> list[Path]:
    return [p for p in task.rglob("*.md") if p.name.lower() != "readme.md" and "data" not in p.parts]


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=[t.name for t in TASKS])
def test_brief_has_no_task_section_and_no_press_enter(task: Path):
    offenders = [f"{b.relative_to(CONTENT)}: {m.group(0)!r}"
                 for b in _briefs(task)
                 for rx in (_TASK_SECTION, _PRESS_ENTER)
                 for m in rx.finditer(b.read_text(encoding="utf-8"))]
    assert not offenders, "\n".join(offenders)
