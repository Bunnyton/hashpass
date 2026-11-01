"""Tier1: every Taskfile bundled under content/tasks/ parses and has at least one stage."""
from pathlib import Path

import pytest

from hashpass.lab.parse import load_labfile
from hashpass.recipe.parse import load_recipe
from tests.content.recipes import is_task_dir, parse_task

TASKS_ROOT = Path(__file__).resolve().parents[2] / "content" / "tasks"

# One id per parametrise case, so a failure names the offending task.
TASKFILES = sorted(p for p in TASKS_ROOT.iterdir() if is_task_dir(p))
LABS = sorted(p for p in TASKS_ROOT.iterdir() if (p / "Labfile").is_file())


@pytest.mark.tier1
@pytest.mark.parametrize("task_dir", TASKFILES, ids=lambda p: p.name)
def test_bundled_taskfile_parses(task_dir: Path) -> None:
    """Parse this task's Taskfile, and sanity-check its shape."""
    recipe = parse_task(task_dir)
    # image ref present
    assert recipe.name, f"{task_dir.name}: missing `image <name>:<version>`"
    assert recipe.version, f"{task_dir.name}: missing image version"
    # at least one stage
    assert recipe.stages, f"{task_dir.name}: no stages defined"
    # the student sees the task's text from the start (stages after it may only check the path)
    assert recipe.stages[0].message, f"{task_dir.name}: no text for the student at the start"
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


@pytest.mark.tier1
@pytest.mark.parametrize("lab_dir", LABS, ids=lambda p: p.name)
def test_every_lab_machine_has_an_image_recipe(lab_dir: Path) -> None:
    """A Labfile's `build <dir>` names a Taskfile that builds an image (no stages: the task is the Labfile)."""
    lab, _ = load_labfile(lab_dir / "Labfile")
    for m in lab.machines:
        if m.build is not None:
            machine = load_recipe(lab_dir / m.build / "Taskfile")
            assert not machine.stages, f"{lab_dir.name}/{m.build}: stages belong in the Labfile"


def _collect_files(recipe) -> set[str]:
    """Every hidden-layer file referenced by `read`/`apply`/bare `exec` in intro/outro and voice."""
    from hashpass.recipe.model import ApplyAction, ExecAction, ReadAction  # noqa: PLC0415
    out: set[str] = set()
    def _grab(action: object) -> None:
        if isinstance(action, (ReadAction, ApplyAction)):
            out.add(action.path)
        elif isinstance(action, ExecAction) and len(action.value.split()) == 1:
            out.add(action.value)          # `exec <cmd args…>` is a shell command, not a file
    for action in (*(recipe.intro or ()), *(recipe.outro or ())):
        _grab(action)
    for st in recipe.stages:
        for action in (st.on_enter or ()):
            _grab(action)
        for action in (st.on_pass or ()):
            _grab(action)
    return out
