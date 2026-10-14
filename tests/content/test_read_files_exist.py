"""Tier1: every `read` file an action names is where the engine looks for it."""
from pathlib import Path

import pytest

from hashpass.recipe.model import ReadAction
from hashpass.recipe.parse import parse_recipe

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TASKS = sorted(p for p in CONTENT.iterdir() if (p / "Taskfile").is_file())


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=lambda p: p.name)
def test_read_files_exist(task: Path) -> None:
    # links (2026-10-14): `hint output "…" read relative.md` showed «(read: файл не найден)» -- a hint's
    # dose is read from the hidden layer hp/, the brief and `on enter` doses from the task folder.
    recipe = parse_recipe((task / "Taskfile").read_text(encoding="utf-8"))
    missing = []
    for st in recipe.stages:
        missing += [f"hint read {h.action.path}" for h in st.hints
                    if isinstance(h.action, ReadAction) and not (task / "hp" / h.action.path).is_file()]
        for a in (*st.on_enter, *st.on_pass):
            if isinstance(a, ReadAction) and not ((task / a.path).is_file() or (task / "hp" / a.path).is_file()):
                missing.append(f"read {a.path}")
    assert not missing, f"{task.name}: {missing}"
