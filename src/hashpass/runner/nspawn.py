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
            subprocess.run(
                ["sudo", "tar", "-xpf", str(self._base_tar), "-C", str(self._lower)],
                check=True,
            )
        elif self._base_dir:
            subprocess.run(
                ["sudo", "rsync", "-a", str(self._base_dir) + "/", str(self._lower) + "/"],
                check=True,
            )
        stack = [Path(p) for p in lowers] + [self._lower]  # first = top
        overlay_mount(stack, self._upper, self._work, self._mnt, sudo=True)

    def run(self, argv: list[str], *, binds: list[tuple[str, str]] | None = None,
            setenv: dict[str, str] | None = None) -> RunResult:
        """
        Run a single command inside the container via systemd-nspawn.

        Args:
            argv: Command and arguments to run.
            binds: Optional (host, dst) pairs bound rw into THIS run's mount-ns only
                (e.g. the hidden `/hp` layer). A run with `binds=None` sees no `/hp`,
                and a bind leaves no trace: its mountpoint is cleaned up afterwards
                so a later plain run cannot see it (§4.2 invisibility-by-namespace).
            setenv: Optional environment variables set inside the container.

        Returns:
            RunResult with stdout, stderr, and exit code.

        """
        extra = [f"--bind={host}:{dst}" for host, dst in binds or []]
        extra += [f"--setenv={key}={val}" for key, val in (setenv or {}).items()]
        p = subprocess.run(
            ["sudo", "systemd-nspawn", "-q", "--register=no",
             *extra, "-D", str(self._mnt), *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        for _host, dst in binds or []:
            self._clean_mountpoint(dst)
        return RunResult(p.stdout, p.stderr, p.returncode)

    def _clean_mountpoint(self, dst: str) -> None:
        """
        Remove a bind mountpoint systemd-nspawn auto-created in the overlay upperdir.

        nspawn creates the bind destination inside the container root; on our overlay
        that mkdir lands in the writable upperdir and outlives the (per-run) mount, so a
        later plain run would see the empty dir — leaking that `/hp` exists (§4.2). It is
        removed THROUGH the overlay with a throwaway nspawn `rmdir` (never by touching the
        upperdir directly, which is illegal under a live overlay and corrupts its cache).
        Best-effort: a non-empty or already-gone mountpoint leaves rmdir a no-op.
        """
        subprocess.run(
            ["sudo", "systemd-nspawn", "-q", "--register=no",
             "-D", str(self._mnt), "rmdir", dst],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def boot(self, machine: str) -> None:
        """
        Boot the container in the background as a registered machine.

        Args:
            machine: Machine name to register with systemd-machined.

        Raises:
            RuntimeError: If the machine does not register within 30 seconds.

        """
        self._proc = subprocess.Popen(
            ["sudo", "systemd-nspawn", "-b", "-q", "-M", machine, "-D", str(self._mnt)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._machine = machine
        for _ in range(30):
            if (
                subprocess.run(
                    ["sudo", "machinectl", "status", machine],
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
        """
        Power off the booted machine and wait for the nspawn process to exit.

        No-op if the machine was never booted.

        """
        if self._proc is None:
            return
        subprocess.run(["sudo", "machinectl", "poweroff", self._machine], check=False)
        self._proc.wait(timeout=30)
        self._proc = None
        self._machine = None

    @property
    def rootfs(self) -> Path:
        """Composed overlay mountpoint (what the container sees as /)."""
        return self._mnt

    @property
    def rootfs_upper(self) -> Path:
        """Writable upperdir where persisted changes land."""
        return self._upper

    def teardown(self) -> None:
        """Power off the machine (if booted) and unmount the overlay stack."""
        self.poweroff()
        overlay_umount(self._mnt, sudo=True)
