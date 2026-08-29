import pytest

from hashpass.image.base import build_base
from hashpass.play import play
from hashpass.runner.nspawn import NspawnRunner


@pytest.mark.tier3
def test_end_to_end_boot_solve_key(tmp_path, base_tar):
    base = build_base(tmp_path / "base", from_tar=base_tar)
    task = tmp_path / "task"
    task.mkdir()
    # /var/tmp, not /root: stub_check reads the rootfs host-side as user
    # debi. /root is 0700 root:root -- debi can't traverse it, so exists()
    # raises PermissionError instead of returning False (confirmed below in
    # the RED run). /tmp is a private ephemeral tmpfs under systemd-nspawn,
    # so writes there never reach the overlay. /var/tmp is 1777 (world
    # traversable) and persists to the overlay, so a root-created file
    # there (mode 644) is stat-able by debi and the check passes.
    (task / "readme.txt").write_text("touch /var/tmp/done.txt", encoding="utf-8")
    (task / "task.toml").write_text(
        'id="demo"\n[check]\nkind="path_exists"\npath="var/tmp/done.txt"\n',
        encoding="utf-8",
    )
    r = NspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([task])
    try:
        assert play(r, task, nonce="n") is None
        r.run(["sh", "-c", "touch /var/tmp/done.txt"])  # student solves
        key = play(r, task, nonce="n")
        assert key and key.startswith("key{")
        print(f"walking skeleton key: {key}")
    finally:
        r.teardown()
