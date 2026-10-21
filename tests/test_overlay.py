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


@pytest.mark.tier1
def test_mount_chatter_never_reaches_the_console(capfd):
    """
    `mount` hints («your fstab has been modified…») went straight to the student's console.

    The helper keeps the tool's output; a failure still raises and carries it.
    """
    from hashpass.overlay import _run  # noqa: PLC0415
    _run(["sh", "-c", "echo noise; echo hint >&2"], False)  # noqa: FBT003
    assert capfd.readouterr() == ("", "")
    with pytest.raises(subprocess.CalledProcessError) as err:
        _run(["sh", "-c", "echo boom >&2; exit 3"], False)  # noqa: FBT003
    assert "boom" in err.value.stderr


@pytest.mark.tier1
def test_a_deep_layer_chain_fits_the_mount_option_limit(tmp_path, monkeypatch):
    """
    Mount a long layer chain through short names.

    libmount hands `lowerdir` to the kernel as one fsconfig string, and over 256 bytes the mount
    fails («wrong fs type, bad option»): a chain of four tasks + the base did not boot. Long
    chains go through short symlinks next to the mountpoint instead.
    """
    from hashpass import overlay  # noqa: PLC0415
    calls: list[list[str]] = []
    cwds: list = []
    monkeypatch.setattr(overlay, "_run",
                        lambda argv, _sudo, cwd=None: calls.append(argv) or cwds.append(cwd))
    layers = [tmp_path / ("images/bunnyton/" + "x" * 40 + f"/{i}/layer") for i in range(6)]
    mnt = tmp_path / "run" / "mnt"
    overlay.overlay_mount(layers, tmp_path / "u", tmp_path / "w", mnt, sudo=False)
    opts = calls[-1][calls[-1].index("-o") + 1]
    lowerdir = opts.split(",")[0].removeprefix("lowerdir=")
    assert len(lowerdir) <= 256  # noqa: PLR2004
    assert [(cwds[-1] / p).resolve(strict=False) for p in lowerdir.split(":")] == [
        p.resolve(strict=False) for p in layers]
    short = [tmp_path / "a", tmp_path / "b"]
    overlay.overlay_mount(short, tmp_path / "u", tmp_path / "w", mnt, sudo=False)
    assert calls[-1][calls[-1].index("-o") + 1].startswith(f"lowerdir={short[0]}:{short[1]},")
    assert cwds[-1] is None
