"""Tier1: the authored sample task.toml files load into well-formed TaskCode."""
from pathlib import Path

import pytest

from hashpass.taskcode.model import TaskCode, load_task_code

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"

EXPECTED = {
    "hello": {
        "setup": (),
        "commands": ("echo hello > hello.txt",),
        "observe": ("hello.txt",),
    },
    "list-files": {
        "setup": ("mkdir -p work", "touch work/a work/b work/c"),
        "commands": ("ls work > listing.txt",),
        "observe": ("listing.txt",),
    },
    "grep-todo": {
        # TOML basic (double-quoted) strings decode \n to a real newline, so the loaded
        # setup command carries actual newlines; printf emits them literally (single-quoted),
        # seeding a 3-line notes.txt.
        "setup": ("printf 'alpha\nTODO fix\nbeta\n' > notes.txt",),
        "commands": ("grep TODO notes.txt > found.txt",),
        "observe": ("found.txt",),
    },
}


@pytest.mark.tier1
@pytest.mark.parametrize("task_id", list(EXPECTED))
def test_sample_task_loads(task_id):
    """Each sample task.toml parses into a one-stage TaskCode with the expected fields."""
    task = load_task_code(CONTENT / task_id / "task.toml")
    exp = EXPECTED[task_id]
    assert isinstance(task, TaskCode)
    assert task.id == task_id
    assert task.setup == exp["setup"]
    assert len(task.stages) == 1
    stage = task.stages[0]
    assert stage.commands == exp["commands"]
    assert stage.observe == exp["observe"]
    assert stage.message
