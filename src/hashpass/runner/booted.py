"""
Booted systemd-nspawn runner: a real booted machine; commands via machinectl (mechanism §1-5).

Limits of the fresh-overlay `/hp` handler branch (`run(binds=...)`, mechanism §4):
  1. FS-snapshot, not live PID. The handler overlay stacks the booted machine's merged
     rootfs (`self._mnt`) as a read-only lower, so a handler sees the student's *files*
     (upper writes + image + base, as the running student sees them) but not the booted
     machine's *live processes*. Process/service acceptance must therefore be
     observe/FS-based (e.g. a stage command writes `pgrep ... > /count.txt`; the
     handler grades the file) -- a handler doing `pgrep` itself would see only its
     own transient namespace.
  2. Racy if written concurrently. The stacked upper is a live directory; the
     snapshot is consistent only because handlers run while the student is idle
     between commands (`TaskSession.feed` runs the student command to completion,
     *then* checks). Documented, accepted.
  3. Handler rootfs writes are discarded. A handler's writes to the container root
     land in the throwaway per-handler upperdir and never reach the live booted
     student; only writes to the bound `/hp` persist (that is how `on_enter`/
     `on_pass`/`state.json` survive). Consequence: an `on_enter` that must seed the
     live student filesystem is unsupported -- seed via the image (`run`/`copy` at
     build time) or via student/`solve` commands instead.
"""
import shlex
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from hashpass.overlay import overlay_mount, overlay_umount
from hashpass.runner.nspawn import NspawnRunner

from .base import RunResult

_RC_ON_MISSING = 1        # exit code when the container never wrote a parseable rc
_MACHINE_PREFIX = "hp-"   # systemd machine-name prefix (hostname-valid)
_MACHINE_HEX = 12         # hex chars of uuid entropy per machine name
_RUN_DIR = ".hp-run"      # overlay-root dot-dir for per-run out/err/rc (hidden from a plain `ls /`)
_BOOT_TIMEOUT = 30        # seconds to wait for machined registration (~2s typical)
_READY_TIMEOUT = 30       # seconds to wait for machinectl-shell/session readiness after boot
_READY_MARKER = ".hp-boot-ready"  # overlay marker for the boot-readiness probe result
_READY_STABLE = 2         # consecutive readiness hits required (avoid a mid-boot race)
_RUN_RETRIES = 8          # machinectl-shell session setup is flaky; retry until the cmd runs
_KILL_TIMEOUT = 10        # seconds to wait after terminating a wedged nspawn process


def _capture_files(out_text: str, err_text: str, rc_text: str) -> RunResult:
    """Assemble a RunResult from the container-written out/err/rc file contents (mechanism §3)."""
    raw = rc_text.strip()
    try:
        code = int(raw)
    except ValueError:
        code = _RC_ON_MISSING
    return RunResult(stdout=out_text, stderr=err_text, exit_code=code)


def _machine_name() -> str:
    """Return a unique, hostname-valid machine name for one booted runner (avoids -M collisions)."""
    return f"{_MACHINE_PREFIX}{uuid4().hex[:_MACHINE_HEX]}"


def _read(path: Path) -> str:
    """Read a container-written file host-side (world-readable 644); '' if it never appeared."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


class BootedNspawnRunner(NspawnRunner):
    """Run commands in a BOOTED systemd-nspawn machine (real PID 1 + services), via machinectl."""

    def prepare(self, lowers: list[Path]) -> None:
        """Mount the overlay (as NspawnRunner) then boot it; atomic — cleans up if boot fails."""
        super().prepare(lowers)
        self._hp = 0                                         # per-handler overlay counter
        try:
            self._boot()
        except Exception:            # boot failed: unmount + kill, then re-raise (ruff: BLE001 exempts re-raise)
            self._kill()
            overlay_umount(self._mnt, sudo=True)
            raise

    def _boot(self) -> None:
        """Boot the overlay in the background and wait for machined registration (mechanism §2)."""
        self._machine = _machine_name()
        self._proc = subprocess.Popen(
            ["sudo", "systemd-nspawn", "-b", "-q", "--register=yes",
             "-M", self._machine, "-D", str(self._mnt)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(_BOOT_TIMEOUT):
            if subprocess.run(["sudo", "machinectl", "status", self._machine],
                              capture_output=True, check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            msg = f"booted machine {self._machine!r} did not register within {_BOOT_TIMEOUT}s"
            raise RuntimeError(msg)
        self._await_shell_ready()

    def _await_shell_ready(self) -> None:
        """Wait until `machinectl shell` reliably runs a command (session infra up post-boot)."""
        marker = self._mnt / _READY_MARKER
        stable = 0
        for _ in range(_READY_TIMEOUT):
            marker.unlink(missing_ok=True)
            subprocess.run(
                ["sudo", "machinectl", "shell", self._machine, "/bin/sh", "-c",
                 f"printf 1 > /{_READY_MARKER}"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            stable = stable + 1 if marker.exists() else 0
            if stable >= _READY_STABLE:
                marker.unlink(missing_ok=True)
                return
            time.sleep(1)
        msg = f"booted machine {self._machine!r} not shell-ready within {_READY_TIMEOUT}s"
        raise RuntimeError(msg)

    def run(self, argv: list[str], *, binds: list[tuple[str, str]] | None = None,
            setenv: dict[str, str] | None = None) -> RunResult:
        """Run in the booted machine (no binds, §3) or on a fresh /hp-bound overlay (binds, §4)."""
        if binds:
            return self._run_handler(argv, binds, setenv or {})
        rundir = f"/{_RUN_DIR}"
        host = self._mnt / _RUN_DIR
        # machinectl's PTY does not pipe stdout: the wrapped command redirects out/err/rc to
        # overlay-backed files read host-side. `cd /` keeps cwd == '/' (non-boot parity). A new
        # machinectl session is flaky, so retry (fresh token) until the wrapper actually runs --
        # a missing rc file means it never executed (no side effect), so retrying is safe.
        for _ in range(_RUN_RETRIES):
            token = uuid4().hex
            wrapped = (f"mkdir -p {rundir}; cd /; {shlex.join(argv)} "
                       f">{rundir}/{token}.out 2>{rundir}/{token}.err; "
                       f"printf %s $? >{rundir}/{token}.rc")
            subprocess.run(
                ["sudo", "machinectl", "shell", self._machine, "/bin/sh", "-c", wrapped],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )  # blocks until the command finishes
            if (host / f"{token}.rc").exists():
                return _capture_files(_read(host / f"{token}.out"),
                                      _read(host / f"{token}.err"),
                                      _read(host / f"{token}.rc"))
        return _capture_files("", "", "")   # never executed after retries -> sentinel rc

    def _run_handler(self, argv: list[str], binds: list[tuple[str, str]],
                     setenv: dict[str, str]) -> RunResult:
        """Run a /hp handler on a FRESH overlay over the booted machine's merged rootfs (§4)."""
        self._hp += 1
        hp = self._wd / f"hp{self._hp}"
        upper, work, mnt = hp / "upper", hp / "work", hp / "mnt"
        for d in (upper, work, mnt):
            d.mkdir(parents=True, exist_ok=True)
        # Stack the booted machine's MERGED rootfs (self._mnt) as one read-only lower: it shows
        # the student's current fs (upper+image+base). Reusing the live upperdir directly fails
        # once the machine is booted; the merged mount is stable to nest under.
        overlay_mount([self._mnt], upper, work, mnt, sudo=True)
        try:
            extra = [f"--bind={host}:{dst}" for host, dst in binds]
            extra += [f"--setenv={key}={val}" for key, val in setenv.items()]
            proc = subprocess.run(
                ["sudo", "systemd-nspawn", "-q", "--register=no",
                 *extra, "-D", str(mnt), *argv],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
        finally:
            overlay_umount(mnt, sudo=True)      # per-handler mnt discarded: invisible + no busy-conflict
        return RunResult(proc.stdout, proc.stderr, proc.returncode)

    def _kill(self) -> None:
        """Terminate the background nspawn process (best-effort) and clear machine state."""
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=_KILL_TIMEOUT)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        # Always clear BOTH, even if _proc was never started: _boot() sets self._machine
        # before Popen, so a Popen failure must not leave a name for a machine that never ran.
        self._proc = None
        self._machine = None

    @property
    def machine(self) -> str:
        """The booted machine's registered name (for `machinectl shell` interactivity)."""
        if self._machine is None:
            msg = "runner is not booted"
            raise RuntimeError(msg)
        return self._machine

    def teardown(self) -> None:
        """Power off the machine then unmount the overlay — robustly, even if poweroff fails."""
        try:
            self.poweroff()
        except Exception:            # noqa: BLE001 - a wedged machine must not block the umount
            self._kill()
        finally:
            overlay_umount(self._mnt, sudo=True)
