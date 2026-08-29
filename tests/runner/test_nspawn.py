import pytest

from hashpass.runner.nspawn import NspawnRunner


@pytest.mark.tier3
def test_nspawn_run_and_persist(tmp_path, base_tar):
    r = NspawnRunner(tmp_path, base_tar=base_tar)
    r.prepare([])
    try:
        res = r.run(["sh", "-c", ". /etc/os-release; echo $ID; id -u"])
        assert res.exit_code == 0
        assert "debian" in res.stdout and "0" in res.stdout
        # /var/tmp is 1777 and root's default umask makes the new file 644,
        # so it's world-readable -- read it back directly from the host-side
        # upperdir. This proves the write actually landed in the overlay
        # upperdir specifically (a wrongly-wired upper= could still pass an
        # in-container-only check like `cat` through the mount).
        #
        # NOTE: this must be /var/tmp, not /tmp -- systemd-nspawn mounts a
        # private, ephemeral tmpfs over /tmp by default (confirmed via
        # `cat /proc/mounts` inside the container: `tmpfs /tmp tmpfs rw,...`),
        # so anything written to /tmp never reaches the overlay at all and
        # the direct upperdir read fails with FileNotFoundError. /var/tmp is
        # not on nspawn's private-mount list, so it round-trips through the
        # overlay like any other ordinary path (verified manually).
        r.run(["sh", "-c", "echo persisted > /var/tmp/p.txt"])
        assert (r.rootfs_upper / "var/tmp/p.txt").read_text(encoding="utf-8").strip() == "persisted"
    finally:
        r.teardown()
