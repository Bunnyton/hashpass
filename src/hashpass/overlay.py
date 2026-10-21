import subprocess
from pathlib import Path


class OverlayError(subprocess.CalledProcessError):
    """A mount/umount failed; unlike CalledProcessError, its message carries what the tool said."""

    def __str__(self) -> str:
        """Show the command + exit status, then the tool's own diagnosis."""
        return f"{super().__str__()}: {(self.stderr or '').strip()}"


# libmount hands each mount option to the kernel as one fsconfig string, and a value over 256
# bytes fails the mount («wrong fs type, bad option»): four task layers + the base already did.
_MAX_LOWERDIR = 200


def _run(argv: list[str], sudo: bool, cwd: Path | None = None) -> None:  # noqa: FBT001
    """
    Run a command, optionally elevated with sudo.

    Args:
        argv: Command and arguments to run.
        sudo: Whether to prefix the command with sudo.
        cwd: Directory to run in (relative paths in `argv` resolve against it).

    The output is kept, not passed through: this runs while the student's console owns the
    terminal, and `mount` hints («your fstab has been modified…») landed in it. A failure still
    raises CalledProcessError, which carries the stderr.

    """
    try:
        subprocess.run((["sudo"] if sudo else []) + argv, check=True, capture_output=True,
                       text=True, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        # the tool's own words are the diagnosis: keep them in the message, not only in .stderr
        raise OverlayError(exc.returncode, exc.cmd, exc.output, exc.stderr) from exc


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
    cwd = None
    if len(lowerdir) > _MAX_LOWERDIR:
        # a deep chain: short relative names (0:1:2…) for symlinks to the layers, resolved
        # against the mount's cwd -- the kernel follows them once, at mount time
        cwd = mnt.parent / f".{mnt.name}-lowers"
        cwd.mkdir(parents=True, exist_ok=True)
        for i, layer in enumerate(lowers):
            link = cwd / str(i)
            link.unlink(missing_ok=True)
            link.symlink_to(Path(layer).resolve())
        lowerdir = ":".join(str(i) for i in range(len(lowers)))
    opts = f"lowerdir={lowerdir},upperdir={upper},workdir={work}"
    _run(["mount", "-t", "overlay", "overlay", "-o", opts, str(mnt)], sudo, cwd)


def overlay_umount(mnt: Path, *, sudo: bool) -> None:
    """
    Unmount a previously mounted overlayfs.

    Args:
        mnt: Mountpoint to unmount.
        sudo: Whether to unmount via sudo (rootless when False).

    """
    _run(["umount", str(mnt)], sudo)
