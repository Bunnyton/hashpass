"""Tests for TaskCode/StageCode model and TOML (de)serialization."""
import pytest

from hashpass.taskcode.model import StageCode, TaskCode, dump_task_code, load_task_code


@pytest.mark.tier1
def test_task_code_toml_round_trip(tmp_path):
    """Test TaskCode round-trip through TOML serialization."""
    task = TaskCode(
        id="demo",
        setup=("mkdir -p work", "echo seeded > work/base.txt"),
        stages=(
            StageCode(
                commands=("cd work", 'echo "answer" > result.txt'),
                observe=("work/result.txt",),
                exclude=("work/tmp",),
                message="Write the answer.",
            ),
            StageCode(
                commands=("sort work/result.txt > work/sorted.txt",),
                observe=("work/sorted.txt",),
            ),
        ),
    )
    path = tmp_path / "task.toml"
    dump_task_code(task, path)
    assert load_task_code(path) == task  # exact round-trip, incl. escaped quotes + defaults
