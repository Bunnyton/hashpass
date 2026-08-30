"""Tier3: end-to-end in a real systemd-nspawn container on the `hello` sample task."""
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.image.base import build_base
from hashpass.play import capture_candidate
from hashpass.runner.nspawn import NspawnRunner
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.model import load_task_code

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"


def _tmpdir_factory(tmp_path: Path) -> Callable[[], TmpdirRunner]:
    """Host-side factory: derive the checks fast, off-container."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


@pytest.mark.tier3
def test_hello_end_to_end_in_nspawn(tmp_path, base_tar):
    """Derive host-side, then accept an in-container solve and reject a wrong one."""
    task = load_task_code(CONTENT / "hello" / "task.toml")
    derived = derive_checks(_tmpdir_factory(tmp_path / "derive"), task, passes=3)
    stage_checks = derived.stages[0]

    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = NspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        # Student solves the task INSIDE the container (cwd is / -> writes /hello.txt).
        r.run(["sh", "-c", "echo hello > hello.txt"])
        candidate = capture_candidate(r.rootfs, stage_checks, last_output="")
        assert check_stage(stage_checks, candidate)

        # A wrong in-container solve is rejected.
        r.run(["sh", "-c", "echo NOPE > hello.txt"])
        wrong = capture_candidate(r.rootfs, stage_checks, last_output="")
        assert not check_stage(stage_checks, wrong)
    finally:
        r.teardown()
