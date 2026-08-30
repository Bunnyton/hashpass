"""Tier1: codegen path — transcript -> TaskCode -> derive -> accept/reject (spec §3)."""
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.play import capture_candidate
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.codegen import StageTranscript, codegen_from_transcript
from hashpass.taskcode.derive import derive_checks


def _factory(tmp_path: Path) -> Callable[[], TmpdirRunner]:
    """Return a factory of fresh, prepared TmpdirRunners under tmp_path."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


@pytest.mark.tier1
def test_codegen_transcript_derives_a_working_check(tmp_path):
    """A recorded transcript becomes code that derives a discriminating check."""
    code = codegen_from_transcript(
        "hello",
        (),
        (StageTranscript(commands=("echo hello > hello.txt",), changed=("hello.txt",)),),
    )
    assert code.id == "hello"
    assert code.stages[0].commands == ("echo hello > hello.txt",)
    assert code.stages[0].observe == ("hello.txt",)

    derived = derive_checks(_factory(tmp_path / "derive"), code, passes=3)
    stage_checks = derived.stages[0]

    # CORRECT solve of the generated task is accepted.
    good = TmpdirRunner(tmp_path / "good")
    good.prepare([])
    out = good.run(["sh", "-c", "echo hello > hello.txt"]).stdout
    assert check_stage(stage_checks, capture_candidate(good.rootfs, stage_checks, out))
    good.teardown()

    # WRONG solve is rejected.
    bad = TmpdirRunner(tmp_path / "bad")
    bad.prepare([])
    out_w = bad.run(["sh", "-c", "echo NOPE > hello.txt"]).stdout
    assert not check_stage(stage_checks, capture_candidate(bad.rootfs, stage_checks, out_w))
    bad.teardown()
