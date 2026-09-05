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
        self._hp = 0                      # per-handler fresh-overlay counter

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
            binds: Optional (host, dst) pairs bound rw into THIS run's mount-ns only (e.g.
                the hidden `/hp` layer). A bind run executes on a FRESH throwaway overlay
                stacked over the student's mount (see `_run_bound`) -- so `/hp` is visible
                only to that handler (invisibility-by-namespace, §4.2) and it never contends
                for `-D <student mnt>`, which a live foreground console holds. A `binds=None`
                run has no `/hp` and executes on the student mount directly.
            setenv: Optional environment variables set inside the container.

        Returns:
            RunResult with stdout, stderr, and exit code.

        """
        if binds:
            return self._run_bound(argv, binds, setenv or {})
        p = subprocess.run(
            # --console=pipe: connect the command's stdio to our pipes directly. Without it nspawn
            # defaults to --console=interactive and ALLOCATES A PTY per run; derivation does dozens
            # of these per build, so the ptys pile up against the global kernel.pty.max and later
            # starve the interactive console's script(1) ("No space left on device").
            ["sudo", "systemd-nspawn", "-q", "--console=pipe", "--register=no",
             "-D", str(self._mnt), *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            stdin=subprocess.DEVNULL,
        )
        return RunResult(p.stdout, p.stderr, p.returncode)

    def _run_bound(self, argv: list[str], binds: list[tuple[str, str]],
                   setenv: dict[str, str]) -> RunResult:
        """
        Run a bind (/hp handler) on a FRESH throwaway overlay stacked over the student mount.

        Stacking the student's merged mount as a read-only lower gives the handler the
        student's CURRENT files while its own writes land in a throwaway upper (discarded);
        `/hp` is bound only here, so the student never sees it, and there is no `-D <student
        mnt>` contention -- which matters because the interactive console boots the student
        mount and holds it. The per-handler mount is unmounted afterwards, leaving no trace.
        """
        self._hp += 1
        hp = self._wd / f"hp{self._hp}"
        upper, work, mnt = hp / "upper", hp / "work", hp / "mnt"
        for d in (upper, work, mnt):
            d.mkdir(parents=True, exist_ok=True)
        overlay_mount([self._mnt], upper, work, mnt, sudo=True)
        try:
            extra = [f"--bind={host}:{dst}" for host, dst in binds]
            extra += [f"--setenv={key}={val}" for key, val in setenv.items()]
            p = subprocess.run(
                # --console=pipe: no per-run pty (see the note in run()); handlers run dozens of
                # times too, so this keeps them off the kernel.pty.max budget.
                ["sudo", "systemd-nspawn", "-q", "--console=pipe", "--register=no",
                 *extra, "-D", str(mnt), *argv],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                stdin=subprocess.DEVNULL,
            )
        finally:
            overlay_umount(mnt, sudo=True)
        return RunResult(p.stdout, p.stderr, p.returncode)

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
        Terminate the booted machine (clean machined deregistration) and reap the process.

        No-op if the machine was never booted.

        """
        if self._proc is None:
            return
        # terminate (not poweroff): immediate kill + clean deregistration from machined. A
        # graceful poweroff often hangs on container shutdown, and killing it then leaks the
        # machine scope -- machined degrades after many machines and new boots fail to register.
        subprocess.run(["sudo", "machinectl", "terminate", self._machine], check=False)
        try:
            self._proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            self._proc.wait(timeout=5)
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
