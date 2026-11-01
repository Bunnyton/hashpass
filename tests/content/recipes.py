"""Content lints see a lab's Labfile wherever they see a task's Taskfile (spec 2026-11-02)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from hashpass.lab.parse import parse_labfile
from hashpass.recipe.parse import parse_recipe

if TYPE_CHECKING:
    from pathlib import Path

    from hashpass.recipe.model import Recipe


def recipe_file(task: Path) -> Path:
    """Return the task's recipe: its Labfile (a lab) or its Taskfile."""
    lab = task / "Labfile"
    return lab if lab.is_file() else task / "Taskfile"


def is_task_dir(path: Path) -> bool:
    """Whether a content folder is a task (a Taskfile or a Labfile)."""
    return (path / "Taskfile").is_file() or (path / "Labfile").is_file()


def parse_task(task: Path) -> Recipe:
    """Parse the task's recipe (a Labfile's task part for a lab)."""
    text = recipe_file(task).read_text(encoding="utf-8")
    return parse_labfile(text)[1] if recipe_file(task).name == "Labfile" else parse_recipe(text)
