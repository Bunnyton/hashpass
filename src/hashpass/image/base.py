import subprocess
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[3] / "runtime"
_SYSTEMD_INSTALL = (
    # chown 0:0 / first: the base dir is created by the unprivileged builder (uid 1000) while
    # its extracted contents are root-owned; systemd's postinst tmpfiles refuses that "unsafe
    # path transition" (/ owned by 1000 -> /etc owned by root) and aborts dpkg. Root-own / to fix.
    "chown 0:0 / && apt-get update "
    "&& apt-get install -y systemd systemd-sysv dbus fish "
    # A known root password (root:hashpass) as a fallback for su/sudo inside the container;
    # the console autologin (runtime drop-in) means it is not needed just to get a shell.
    "&& echo 'root:hashpass' | chpasswd"
)


def _wipe_tree(path: Path) -> None:
    """Empty a possibly root-owned dir tree using only granted-sudo commands (no sudo rm)."""
    empty = path.parent / f".empty-{path.name}"
    empty.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["sudo", "rsync", "-a", "--delete", str(empty) + "/", str(path) + "/"],
            check=True,
        )
    finally:
        empty.rmdir()


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
    if ((dest / "lib/systemd/systemd").exists() and (dest / "usr/bin/hash").exists()
            and (dest / "usr/local/sbin/hp-console").exists()):
        # Already a COMPLETE bootable base (systemd from apt + runtime from rsync, including
        # the console-autologin script): reuse it. Rebuilding would re-extract the tar over an
        # apt-configured tree and corrupt dpkg, and it avoids rebuilding the invariant base on
        # every build/build_task/run. ALL markers are required, so a stale pre-systemd base, a
        # half-built one, or a pre-autologin base (no hp-console) is rebuilt from scratch.
        return dest
    if dest.exists():
        _wipe_tree(dest)  # stale/partial tree -> clear it so the fresh tar extracts clean
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["sudo", "tar", "-xpf", str(from_tar), "-C", str(dest)],
        check=True,
    )
    # Make the base BOOTABLE + interactive: systemd (PID 1), dbus (machinectl), fish (the shell).
    # Deliberately MINIMAL — task tools like procps/ps are installed by tasks, never baked in
    # (else a stage that checks for them passes before the student has done anything).
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
