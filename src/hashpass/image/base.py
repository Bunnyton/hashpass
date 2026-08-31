import subprocess
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[3] / "runtime"
_SYSTEMD_INSTALL = "apt-get update && apt-get install -y systemd systemd-sysv dbus procps"


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
    # Make the base BOOTABLE: install systemd (PID 1), dbus (machinectl), procps (ps/pgrep).
    # Non-boot install; run once per base build (Phase 7 — every task runs in a booted machine).
    subprocess.run(
        ["sudo", "systemd-nspawn", "-q", "--register=no", "-D", str(dest),
         "sh", "-c", _SYSTEMD_INSTALL],
        check=True,
    )
    # Runtime layer (usr/bin/hash + .hash) in a single rsync -- only granted-sudo commands.
    subprocess.run(
        ["sudo", "rsync", "-a", str(_RUNTIME) + "/", str(dest) + "/"],
        check=True,
    )
    return dest
