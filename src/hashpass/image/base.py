import subprocess
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[3] / "runtime"


def build_base(dest: Path, *, from_tar: Path) -> Path:
    """
    Build a base rootfs: extract a Debian rootfs, then overlay the runtime tree.

    Args:
        dest: Directory to build the base image into.
        from_tar: Rootfs tarball to extract as the image's foundation.

    Returns:
        Path to the built base image (a directory).

    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["sudo", "tar", "-xpf", str(from_tar), "-C", str(dest)],
        check=True,
    )
    # Runtime layer (usr/bin/hash + .hash) in a single rsync -- only granted-sudo commands.
    subprocess.run(
        ["sudo", "rsync", "-a", str(_RUNTIME) + "/", str(dest) + "/"],
        check=True,
    )
    return dest
