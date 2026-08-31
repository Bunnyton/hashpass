import pytest

from hashpass.image.base import build_base
from hashpass.runner.booted import BootedNspawnRunner


@pytest.mark.tier3
def test_booted_run_sees_real_systemd_and_persists(tmp_path, base_tar):
    # Booting needs a systemd-bearing base: build_base (Task 1) installs it.
    # The raw base_tar (trixie-slim) is NOT bootable -> always boot from a built base_dir.
    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = BootedNspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        # PID 1 is systemd, journald is up -> a real booted system (not a bare -D run).
        res = r.run(["sh", "-c", "ps -p 1 -o comm="])
        assert res.exit_code == 0
        assert "systemd" in res.stdout
        # exit code round-trips
        assert r.run(["sh", "-c", "exit 7"]).exit_code == 7  # noqa: PLR2004
        # writes persist in the booted overlay upperdir (absolute path -> /var/tmp round-trips)
        r.run(["sh", "-c", "echo persisted > /var/tmp/p.txt"])
        assert (r.rootfs_upper / "var/tmp/p.txt").read_text(encoding="utf-8").strip() == "persisted"
    finally:
        r.teardown()
