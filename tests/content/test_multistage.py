"""Tier1: the multi-stage `fruit-count` task derives and advances stage-by-stage."""
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.play import PlaySession
from hashpass.progress import StageStatus, new_progress
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.bundle import Bundle, dump_bundle, load_bundle
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.model import TaskCode, load_task_code

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TS = "2026-08-30T12:00:00Z"
N_STAGES = 3


def _factory(tmp_path: Path) -> Callable[[], TmpdirRunner]:
    """Build a factory of fresh, prepared TmpdirRunners (one per derive pass)."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"d{next(counter)}")
        r.prepare([])
        return r

    return make


def _student(tmp_path: Path, task: TaskCode) -> TmpdirRunner:
    """Build a persistent student runner with the environment seeded (setup run once)."""
    r = TmpdirRunner(tmp_path / "student")
    r.prepare([])
    r.run(["sh", "-c", "\n".join(task.setup)])
    return r


@pytest.mark.tier1
def test_fruit_count_advances_through_all_three_stages(tmp_path):
    task = load_task_code(CONTENT / "fruit-count" / "task.toml")
    assert len(task.stages) == N_STAGES

    derived = derive_checks(_factory(tmp_path / "derive"), task, passes=3)
    dump_bundle(Bundle(checks=derived, conditions={}, hints={}), tmp_path / "bundle")
    bundle = load_bundle(tmp_path / "bundle")

    session = PlaySession(bundle, new_progress(task.id, N_STAGES), student_id="alice", nonce="n1")
    student = _student(tmp_path, task)
    # Solve each stage in order; every feed must advance + mint a local key.
    for i, stage in enumerate(task.stages):
        out = student.run(["sh", "-c", "\n".join(stage.commands)]).stdout
        result = session.feed(command=stage.commands[-1], rootfs=student.rootfs,
                              last_output=out, ts=TS)
        assert result.advanced, f"stage {i} did not advance"
        assert result.local_key.startswith("key{")
    assert session.progress.statuses == [StageStatus.PASSED_LOCAL] * N_STAGES
    student.teardown()


@pytest.mark.tier1
def test_fruit_count_wrong_middle_stage_stays_locked(tmp_path):
    task = load_task_code(CONTENT / "fruit-count" / "task.toml")
    derived = derive_checks(_factory(tmp_path / "derive"), task, passes=3)
    bundle = Bundle(checks=derived, conditions={}, hints={})

    session = PlaySession(bundle, new_progress(task.id, N_STAGES), student_id="alice", nonce="n1")
    student = _student(tmp_path, task)

    # Stage 0 solved correctly -> advances to stage 1.
    student.run(["sh", "-c", "\n".join(task.stages[0].commands)])
    assert session.feed(command="sort fruits.txt > sorted.txt", rootfs=student.rootfs,
                        last_output="", ts=TS).advanced

    # Stage 1 solved WRONG -> stays locked, no key.
    student.run(["sh", "-c", "echo WRONG > unique.txt"])
    bad = session.feed(command="echo WRONG > unique.txt", rootfs=student.rootfs,
                       last_output="", ts=TS)
    assert not bad.advanced
    assert bad.local_key is None
    assert session.progress.statuses[1] is StageStatus.OPEN
    student.teardown()
