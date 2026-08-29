import os
import subprocess

import pytest


@pytest.mark.tier2
def test_rootless_overlay_write_lands_in_upper(tmp_path):
    low, up, wk, mnt = (tmp_path / d for d in ("low", "up", "wk", "mnt"))
    for d in (low, up, wk, mnt):
        d.mkdir()
    (low / "base.txt").write_text("base", encoding="utf-8")
    # rootless: run inside a user+mount namespace via unshare
    script = f"""
from hashpass.overlay import overlay_mount, overlay_umount
from pathlib import Path
overlay_mount([Path("{low}")], Path("{up}"), Path("{wk}"), Path("{mnt}"), sudo=False)
assert (Path("{mnt}")/"base.txt").read_text(encoding="utf-8") == "base"
(Path("{mnt}")/"new.txt").write_text("x", encoding="utf-8")
overlay_umount(Path("{mnt}"), sudo=False)
assert (Path("{up}")/"new.txt").read_text(encoding="utf-8") == "x"
print("OK")
"""
    r = subprocess.run(
        ["unshare", "-Umr", "python3", "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONPATH": "src"},
        check=False,
    )
    assert "OK" in r.stdout, r.stderr
