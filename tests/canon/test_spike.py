import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.canon import Observation, capture, derive_canonical, matches, run_noise
from hashpass.runner.tmpdir import TmpdirRunner


def _runner_run_once(
    tmp_path: Path, sol_cmds: list[str], observe: list[str],
) -> Callable[[], Observation]:
    counter = itertools.count()

    def run_once() -> Observation:
        r = TmpdirRunner(tmp_path / f"r{next(counter)}")
        r.prepare([])
        for c in sol_cmds:
            r.run(["sh", "-c", c])
        run_noise(r)
        obs = capture(r.rootfs, observe)
        r.teardown()
        return obs

    return run_once


@pytest.mark.tier2
def test_spike_deterministic_stable_and_discriminating(tmp_path):
    observe = ["result.txt"]
    ref = ["echo answer > result.txt"]
    canon = derive_canonical(_runner_run_once(tmp_path, ref, observe), k=3)
    assert canon["result.txt"].text.strip() == "answer"
    assert matches(canon, _runner_run_once(tmp_path, ref, observe)())
    wrong = _runner_run_once(tmp_path, ["echo WRONG > result.txt"], observe)()
    assert not matches(canon, wrong)


@pytest.mark.tier2
def test_spike_time_noise_auto_pruned(tmp_path):
    # ref writes a STABLE answer + a VOLATILE nanosecond timestamp
    observe = ["result.txt", "time.txt"]
    ref = ["echo answer > result.txt", "date +%s%N > time.txt"]
    canon = derive_canonical(_runner_run_once(tmp_path, ref, observe), k=3)
    # THE core bet: volatile field auto-pruned, stable field kept
    assert "result.txt" in canon
    assert "time.txt" not in canon
    # a correct solution at a different time still matches (timestamp not checked)
    assert matches(canon, _runner_run_once(tmp_path, ref, observe)())
    # a wrong result is rejected even though it also carries a (different) timestamp
    wrong = _runner_run_once(
        tmp_path, ["echo WRONG > result.txt", "date +%s%N > time.txt"], observe)()
    assert not matches(canon, wrong)
