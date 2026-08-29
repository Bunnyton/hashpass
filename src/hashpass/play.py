from pathlib import Path

from .check import stub_check
from .key import local_key
from .runner.base import Runner
from .task import Task


def play(runner: Runner, task_dir: Path, *, nonce: str) -> str | None:
    task = Task.load(Path(task_dir))
    if stub_check(runner.rootfs, task.check):
        return local_key(task.id, 0, nonce)
    return None
