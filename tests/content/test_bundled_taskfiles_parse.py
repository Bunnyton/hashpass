"""Tier1: every Taskfile bundled under content/tasks/ parses and has at least one stage."""
from pathlib import Path

import pytest

from hashpass.recipe.parse import parse_recipe

TASKS_ROOT = Path(__file__).resolve().parents[2] / "content" / "tasks"

# One id per parametrise case, so a failure names the offending task.
TASKFILES = sorted(p.parent for p in TASKS_ROOT.glob("*/Taskfile"))


@pytest.mark.tier1
@pytest.mark.parametrize("task_dir", TASKFILES, ids=lambda p: p.name)
def test_bundled_taskfile_parses(task_dir: Path) -> None:
    """Parse this task's Taskfile, and sanity-check its shape."""
    text = (task_dir / "Taskfile").read_text(encoding="utf-8")
    recipe = parse_recipe(text)
    # image ref present
    assert recipe.name, f"{task_dir.name}: missing `image <name>:<version>`"
    assert recipe.version, f"{task_dir.name}: missing image version"
    # at least one stage
    assert recipe.stages, f"{task_dir.name}: no stages defined"
    # every stage has a message the student sees
    for i, st in enumerate(recipe.stages):
        assert st.message, f"{task_dir.name}: stage {i} has empty message"
    # any hidden layer referenced must actually exist under this task dir
    hidden = recipe.hidden
    if hidden:
        assert (task_dir / hidden).is_dir(), (
            f"{task_dir.name}: hidden '{hidden}' listed in Taskfile but no dir {task_dir / hidden}")
    # any read/exec target from top-level or stage voice must actually exist
    for name in _collect_files(recipe):
        found = (task_dir / name).exists()
        if hidden:
            found = found or (task_dir / hidden / name).exists()
        assert found, f"{task_dir.name}: voice references '{name}' but no such file"


def _collect_files(recipe) -> set[str]:
    """Every file name referenced by `read`/`exec` in intro/outro and per-stage voice."""
    from hashpass.recipe.model import ExecAction, ReadAction   # local import: tier1 module
    out: set[str] = set()
    def _grab(action: object) -> None:
        if isinstance(action, ReadAction):
            out.add(action.path)
        elif isinstance(action, ExecAction):
            out.add(action.value)
    for action in (*(recipe.intro or ()), *(recipe.outro or ())):
        _grab(action)
    for st in recipe.stages:
        for action in (st.on_enter or ()):
            _grab(action)
        for action in (st.on_pass or ()):
            _grab(action)
    return out
