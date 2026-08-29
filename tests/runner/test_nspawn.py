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
        r.run(["sh", "-c", "echo persisted > /root/p.txt"])
        # /root is 0700 root:root (standard Debian), so a non-root test process
        # cannot traverse into upper/root/ to read it directly; fall back to
        # reading it back through nspawn (as root) in that expected case.
        try:
            direct = (r.rootfs_upper / "root/p.txt").read_text(encoding="utf-8").strip()
        except PermissionError:
            direct = None
        assert direct == "persisted" or \
            r.run(["cat", "/root/p.txt"]).stdout.strip() == "persisted"
    finally:
        r.teardown()
