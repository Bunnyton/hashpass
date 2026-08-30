import pytest

from hashpass.canon.capture import capture
from hashpass.canon.noise import run_noise
from hashpass.runner.tmpdir import TmpdirRunner


@pytest.mark.tier2
def test_noise_perturbs_but_does_not_touch_observed(tmp_path):
    r = TmpdirRunner(tmp_path / "run")
    r.prepare([])
    r.run(["sh", "-c", "echo answer > result.txt"])
    before = capture(r.rootfs, ["result.txt"])
    run_noise(r)
    after = capture(r.rootfs, ["result.txt"])
    assert before == after  # observed path unchanged by noise
    r.teardown()
