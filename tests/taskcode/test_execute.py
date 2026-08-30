import pytest

from hashpass.canon import FileState
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.execute import run_stage
from hashpass.taskcode.model import StageCode, TaskCode


@pytest.mark.tier1
def test_run_stage_captures_state_and_own_output(tmp_path):
    r = TmpdirRunner(tmp_path / "run")
    r.prepare([])
    task = TaskCode(
        id="t",
        setup=("echo SETUP_NOISE",),
        stages=(
            StageCode(commands=("echo hi > out.txt", "echo OUT"), observe=("out.txt",)),
        ),
    )
    obs = run_stage(r, task, 0)
    assert obs["out.txt"] == FileState("file", "hi\n")
    assert obs["<output>"] == FileState("file", "OUT\n")   # target stage's own stdout
    assert "SETUP_NOISE" not in obs["<output>"].text        # setup/prep stdout NOT leaked
    r.teardown()


@pytest.mark.tier1
def test_run_stage_drops_excluded_prefix(tmp_path):
    r = TmpdirRunner(tmp_path / "run")
    r.prepare([])
    task = TaskCode(
        id="t",
        setup=(),
        stages=(
            StageCode(
                commands=("mkdir -p logs", "echo keep > logs/keep.txt",
                          "echo drop > logs/drop.tmp"),
                observe=("logs",),
                exclude=("logs/drop",),
            ),
        ),
    )
    obs = run_stage(r, task, 0)
    assert "logs/keep.txt" in obs
    assert "logs/drop.tmp" not in obs   # dropped by exclude prefix
    r.teardown()
