import subprocess
from pathlib import Path


def _run(argv: list[str], sudo: bool) -> None:  # noqa: FBT001
    """
    Run a command, optionally elevated with sudo.

    Args:
        argv: Command and arguments to run.
        sudo: Whether to prefix the command with sudo.

    """
    subprocess.run((["sudo"] if sudo else []) + argv, check=True)


def overlay_mount(
    lowers: list[Path],
    upper: Path,
    work: Path,
    mnt: Path,
    *,
    sudo: bool,
) -> None:
    """
    Mount an overlayfs composed of the given layers.

    Args:
        lowers: Lower (read-only) directories, topmost first.
        upper: Upper (writable) directory.
        work: Overlayfs work directory.
        mnt: Mountpoint for the composed filesystem.
        sudo: Whether to mount via sudo (rootless when False).

    """
    lowerdir = ":".join(str(p) for p in lowers)  # first = topmost
    opts = f"lowerdir={lowerdir},upperdir={upper},workdir={work}"
    _run(["mount", "-t", "overlay", "overlay", "-o", opts, str(mnt)], sudo)


def overlay_umount(mnt: Path, *, sudo: bool) -> None:
    """
    Unmount a previously mounted overlayfs.

    Args:
        mnt: Mountpoint to unmount.
        sudo: Whether to unmount via sudo (rootless when False).

    """
    _run(["umount", str(mnt)], sudo)
