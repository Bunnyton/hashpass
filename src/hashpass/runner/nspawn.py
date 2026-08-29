import subprocess
import time
from pathlib import Path

from hashpass.overlay import overlay_mount, overlay_umount

from .base import RunResult


class NspawnRunner:
    """Run commands in a real systemd-nspawn container (production driver)."""

    def __init__(
        self,
        workdir: Path,
        *,
        base_tar: Path | None = None,
        base_dir: Path | None = None,
    ) -> None:
        """
        Initialize with a work directory and a base rootfs source.

        Args:
            workdir: Path to the work directory (holds lower/upper/work/mnt).
            base_tar: Optional tarball to extract as the base rootfs layer.
            base_dir: Optional directory to copy as the base rootfs layer.

        """
        self._wd = Path(workdir)
        self._base_tar, self._base_dir = base_tar, base_dir
        self._lower = self._wd / "lower"
        self._upper = self._wd / "upper"
        self._work = self._wd / "work"
        self._mnt = self._wd / "mnt"
        self._proc: subprocess.Popen | None = None
        self._machine: str | None = None

    def prepare(self, lowers: list[Path]) -> None:
        """
        Extract the base rootfs and mount the overlay stack.

        Args:
            lowers: Extra read-only layers, topmost first. The extracted/copied
                base rootfs is appended below them as the bottommost layer.

        """
        for d in (self._lower, self._upper, self._work, self._mnt):
            d.mkdir(parents=True, exist_ok=True)
        if self._base_tar:
            subprocess.run(  # noqa: S603
                ["sudo", "tar", "-xpf", str(self._base_tar), "-C", str(self._lower)],  # noqa: S607
                check=True,
            )
        elif self._base_dir:
            subprocess.run(  # noqa: S603
                ["sudo", "rsync", "-a", str(self._base_dir) + "/", str(self._lower) + "/"],  # noqa: S607
                check=True,
            )
        stack = [Path(p) for p in lowers] + [self._lower]  # first = top
        overlay_mount(stack, self._upper, self._work, self._mnt, sudo=True)

    def run(self, argv: list[str]) -> RunResult:
        """
        Run a single command inside the container via systemd-nspawn.

        Args:
            argv: Command and arguments to run.

        Returns:
            RunResult with stdout, stderr, and exit code.

        """
        p = subprocess.run(  # noqa: S603
            ["sudo", "systemd-nspawn", "-q", "--register=no", "-D", str(self._mnt), *argv],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return RunResult(p.stdout, p.stderr, p.returncode)

    def boot(self, machine: str) -> None:
        """
        Boot the container in the background as a registered machine.

        Args:
            machine: Machine name to register with systemd-machined.

        Raises:
            RuntimeError: If the machine does not register within 30 seconds.

        """
        self._proc = subprocess.Popen(  # noqa: S603
            ["sudo", "systemd-nspawn", "-b", "-q", "-M", machine, "-D", str(self._mnt)],  # noqa: S607
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._machine = machine
        for _ in range(30):
            if (
                subprocess.run(  # noqa: S603
                    ["sudo", "machinectl", "status", machine],  # noqa: S607
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            ):
                return
            time.sleep(1)
        msg = "machine did not register"
        raise RuntimeError(msg)

    def poweroff(self) -> None:
        """Power off the booted machine and wait for the nspawn process to exit."""
        subprocess.run(["sudo", "machinectl", "poweroff", self._machine], check=False)  # noqa: S603, S607
        self._proc.wait(timeout=30)

    @property
    def rootfs(self) -> Path:
        """Composed overlay mountpoint (what the container sees as /)."""
        return self._mnt

    @property
    def rootfs_upper(self) -> Path:
        """Writable upperdir where persisted changes land."""
        return self._upper

    def teardown(self) -> None:
        """Unmount the overlay stack."""
        overlay_umount(self._mnt, sudo=True)
