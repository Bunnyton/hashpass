import itertools

import pytest

from hashpass.canon import FileState
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.bundle import Bundle, dump_bundle, load_bundle
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.execute import run_stage
from hashpass.taskcode.model import StageCode, TaskCode


def _stage(result_cmd: str) -> tuple[StageCode, ...]:
    return (
        StageCode(
            commands=(result_cmd, "date +%s%N > time.txt"),
            observe=("result.txt", "time.txt"),
        ),
    )


def _fresh(tmp_path, name) -> TmpdirRunner:
    r = TmpdirRunner(tmp_path / name)
    r.prepare([])
    return r


@pytest.mark.tier1
def test_end_to_end_derive_bundle_check_discriminates(tmp_path):
    task = TaskCode(id="sort-demo", setup=(), stages=_stage("echo answer > result.txt"))

    counter = itertools.count()

    def factory() -> TmpdirRunner:
        return _fresh(tmp_path, f"derive{next(counter)}")

    derived = derive_checks(factory, task, passes=3)
    dump_bundle(Bundle(checks=derived, conditions={}, hints={}), tmp_path / "bundle")
    stage_checks = load_bundle(tmp_path / "bundle").checks.stages[0]

    # the volatile timestamp was pruned; the stable result survived
    assert "time.txt" not in stage_checks.canonical
    assert stage_checks.canonical["result.txt"] == FileState("file", "answer\n")

    # CORRECT solution (fresh runner, different timestamp) → ACCEPT
    good = run_stage(_fresh(tmp_path, "good"), task, 0)
    assert check_stage(stage_checks, good)

    # WRONG solution → REJECT (a vacuous always-True checker would fail here)
    wrong_task = TaskCode(id="sort-demo", setup=(), stages=_stage("echo WRONG > result.txt"))
    wrong = run_stage(_fresh(tmp_path, "wrong"), wrong_task, 0)
    assert not check_stage(stage_checks, wrong)
