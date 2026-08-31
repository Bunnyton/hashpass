# Booted Task Runtime (Phase 7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every task builds **and** runs in a real **booted** `systemd-nspawn` machine — a live Linux system with `systemd` PID 1, services, and persistent processes — so process/service tasks are realistic and interactive. This replaces the current per-command **non-boot** (`systemd-nspawn -D`) execution for the derivation and student-runtime paths. Grading (derived observe-file acceptance), the hidden `/hp` handler contract (`check`-exec, hints, `on enter`/`on pass`), and `/hp` invisibility are **all preserved** — the only thing that changes downstream is *which* `Runner` is instantiated.

**Architecture:** A new `runner/booted.py::BootedNspawnRunner` **subclasses** the merged `runner/nspawn.py::NspawnRunner` and honors the same `Runner` protocol (`prepare(lowers)`, `run(argv, *, binds, setenv) -> RunResult`, `rootfs`, `teardown()`), so `taskcode.execute.run_stage`, `canon.capture`, `grade`, `taskrun.TaskSession`, and `handler.run_handler` stay **unchanged**. `prepare()` mounts the overlay (reusing the parent) then **boots** it as a background machine; a plain `run()` (no binds — the student/derive path) executes inside the booted machine via `machinectl shell` with output **redirected to files** read back host-side (the PTY does not pipe stdout); a `run()` **with** binds (the `/hp` handler path) mounts a **fresh, separate overlay** that stacks the *live booted upperdir* + the same lowers + base, runs a non-boot `nspawn --bind --setenv` on it, and unmounts — because a booted machine holds its own mount **exclusively**. `image.base.build_base` gains a one-time `systemd`/`dbus`/`procps` install so the base is bootable. Wiring: the `taskbuild.build_task` derive `factory()`, the `taskrun.run_task` student runner, and `build.run_image` switch to `BootedNspawnRunner`; the plain non-boot `NspawnRunner` is **kept** for the internal image-`build` step (running `run`/`copy` recipe steps at build time does not boot).

**Tech Stack:** Python 3.13, stdlib only (`subprocess`, `shlex`, `uuid`, `pathlib`, `time`). Consumes in-repo `hashpass.overlay`, `hashpass.runner.nspawn`, `hashpass.runner.base`. Real `systemd-nspawn` + `machinectl` + scoped `sudo` for the booted paths (tier3). No third-party deps.

**Spec:** `docs/Архитектура (architecture).md` — §1 (execution: `systemd-nspawn` + `overlayfs`), §4 (acceptance: captured FS/output within tolerance), §10 (tiers). `docs/Образы (images).md` (overlay layers). Predecessor: `docs/superpowers/plans/2026-08-31-task-runtime.md` (Phase 2B — the `/hp` `HP_*` contract, invisibility-by-namespace, and `TaskSession` this phase runs **on a booted machine** without changing them).

## The proven container mechanism (live-probed; transcribe verbatim)

All commands below are **verified working** within the granted `NOPASSWD` sudo set: `systemd-nspawn`, `machinectl`, `mount`, `umount`, `tar`, `rsync`, `systemctl` (confirmed via `sudo -l`). **NOT available:** `systemd-run`, `nsenter`, `sudo cat`, `sudo rm` — none appear anywhere in this plan. Commands run *inside* the booted machine (via `machinectl shell`, as container-root) are the container's own binaries and are unrestricted; the sudo scope only governs *host* commands.

1. **systemd base (one-time, `build_base`):** after extracting the base tar, install systemd non-boot:
   `sudo systemd-nspawn -q --register=no -D <base> sh -c "apt-get update && apt-get install -y systemd systemd-sysv dbus procps"`.
   Result: `/lib/systemd/systemd` present; the base is bootable and has `ps`/`pgrep`. (`debian:trixie-slim` ships none of these.)
2. **Boot (`prepare`):** overlay-mount as today (`overlay_mount([*lowers, base], upper, work, mnt, sudo=True)`), then `sudo systemd-nspawn -b -q --register=yes -M <machine> -D <mnt>` as a **background** process; poll `sudo machinectl status <machine>` until it returns 0 (~2s; timeout ~30s). Booting **on the overlay** works.
3. **Run a student command / solve (`run`, no binds):** the `machinectl shell` PTY does not pipe stdout, so **redirect to files** and read them host-side (container files are mode 644 = world-readable → plain `Path.read_text()` as the unprivileged user, **no sudo**):
   `sudo machinectl shell <machine> /bin/sh -c "<cmd> >/…/<uuid>.out 2>/…/<uuid>.err; printf %s $? >/…/<uuid>.rc"` (blocks until done); then read `<mnt>/…/<uuid>.out|.err|.rc` → `RunResult`. Sees real processes (systemd PID 1, journald, dbus, logind; `ps aux` works).
4. **Run a `/hp` handler (`run` WITH binds/setenv):** a booted machine holds its `<mnt>` **exclusively** (a 2nd `nspawn -D <mnt>` → "Directory tree … is currently busy"). So run the handler on a **separate fresh overlay** stacking the booted machine's live upperdir + the lowers + base, on its **own** mnt, with `/hp` bound:
   `sudo mount -t overlay overlay -o lowerdir=<booted_upper>:<lowers…>:<base>,upperdir=<h_up>,workdir=<h_wk> <h_mnt>`
   then `sudo systemd-nspawn -q --register=no --bind=<hp>:/hp --setenv=HP_…=… -D <h_mnt> <argv>` → capture → `sudo umount <h_mnt>`. Verified: the handler sees the student's files (via the stacked upper) **and** `/hp/*`, with no busy-conflict.
5. **Teardown:** `sudo machinectl poweroff <machine>`; wait for the nspawn process; `overlay_umount(<mnt>, sudo=True)`. Robust in a `finally` (a stale machine + mount must be cleaned even on failure). Unique `-M` name per runner.

## Global Constraints

- Python 3.13; stdlib + in-repo only; `encoding="utf-8"` on **all** file I/O and text subprocess capture.
- ruff `select=["ALL"]` clean under the repo `ruff.toml` (line-length 96; the project ignore-list already covers `ANN201`/`ANN001`, `D100`/`D102`/`D103`/`D104`, `T201`, `E501`, `S101`, `S603`/`S607`, `UP012`, etc.). Module-level constants for `PLR2004` magic values; keep functions ≤5 params (`PLR0913`/`PLR0917`); `# noqa: <code>` only where the repo already does (a `# noqa: BLE001` on each cleanup-then-reraise `except` is the one addition — teardown/prepare must always reach the umount).
- **Tiers:** the three pure helpers (`_capture_files`, `_machine_name`, `_handler_lowers`) are **tier1** (no containers). Everything that boots, `machinectl`-shells, or mounts is **tier3** (`@pytest.mark.tier3`; real `systemd-nspawn` + `machinectl` + scoped sudo). The default `addopts = -m 'not tier3'` keeps normal runs green; the implementer validates the container code with `pytest -m tier3`.
- Match existing runner style: keep `subprocess.run(..., capture_output=True, text=True, encoding="utf-8", check=False)`; argv-form only (no `shell=True`); frozen/plain dataclasses; single-line docstrings.
- **Preserve the `Runner` protocol.** `BootedNspawnRunner` is-a `NspawnRunner` is-a `Runner`, so every existing `NspawnRunner`-typed hint (`taskrun.TaskSession.student`, `perform_action(runner=…)`, `handler.run_handler(runner=…)`, the `Callable[[], NspawnRunner]` factories) stays **valid unchanged**; the wiring task only swaps the class that is *instantiated*.
- **Boundary:** still **local-only**, no deploy, no remote push (see [[rebuild-safety-boundaries]]). Nothing here touches the real server.
- **Perf reality (documented, accepted):** every derivation pass now boots (~2s each) and `build_base` now runs `apt-get install` (one-time per base-dir build; a full task build/run builds the base 2–3×). Keep `passes=2` in tests. This is the cost of the "always booted" requirement; an optional future optimization (cache one bootable base dir and reuse it) is noted in Open Items, out of scope here.

---

### Task 1: Bootable base — `build_base` installs systemd (proven mechanism §1)

**Files:**
- Modify: `src/hashpass/image/base.py` (add the systemd-install step)
- Modify: `tests/image/test_base.py` (assert bootability; keep the runtime assertions)

**Interfaces:**
- `build_base(dest: Path, *, from_tar: Path) -> Path` — signature **unchanged**; the returned base dir now additionally contains `/lib/systemd/systemd` and `procps` (`ps`/`pgrep`).

**Tier:** tier3 (needs `systemd-nspawn` + `apt`; network for `apt-get`).

- [ ] **Step 1: Write the failing test** — extend `tests/image/test_base.py` (keep `test_build_base_has_runtime`):

```python
@pytest.mark.tier3
def test_build_base_is_bootable(tmp_path, base_tar):
    base = build_base(tmp_path / "base", from_tar=base_tar)
    # systemd installed -> base can be booted with `systemd-nspawn -b`
    assert (base / "lib/systemd/systemd").exists()
    # procps installed -> process tasks have ps/pgrep
    assert (base / "usr/bin/pgrep").exists()
```

- [ ] **Step 2: Run to verify it fails** — `python3 -m pytest tests/image/test_base.py -m tier3 -v`
  Expected: FAIL — `trixie-slim` has no `/lib/systemd/systemd` (nor `pgrep`).

- [ ] **Step 3: Implement** — in `src/hashpass/image/base.py`, add a module constant and the install step **after** the tar extract, **before** the runtime rsync (so the runtime layer stays topmost):

```python
_SYSTEMD_INSTALL = "apt-get update && apt-get install -y systemd systemd-sysv dbus procps"
```

```python
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
```

- [ ] **Step 4: Run to verify it passes** — `python3 -m pytest tests/image/test_base.py -m tier3 -v` → PASS (2 tests). `ruff check --config ruff.toml src/hashpass/image/base.py tests/image/test_base.py` clean.

Note: non-boot callers (the `build` image step, the direct-`NspawnRunner` tier3 tests) are unaffected — systemd is merely *present*, not PID 1, when the base is used via `-D`.

- [ ] **Step 5: Commit** — `git commit -m "feat(image): build_base installs systemd/dbus/procps so the base is bootable"`

---

### Task 2: `BootedNspawnRunner` — pure helpers + boot + run (no-binds §3 and /hp §4) + teardown

**Files:**
- Create: `src/hashpass/runner/booted.py`
- Test: `tests/runner/test_booted_pure.py` (new, tier1 — the three pure helpers)
- Test: `tests/runner/test_booted.py` (new, tier3 — boot + no-binds run + persistence; the `/hp` branch is proven in Task 3)

**Interfaces:**
- Consumes: `hashpass.overlay` (`overlay_mount`, `overlay_umount`), `hashpass.runner.nspawn.NspawnRunner`, `hashpass.runner.base.RunResult`.
- Produces:
  - `_capture_files(out_text: str, err_text: str, rc_text: str) -> RunResult` — parse the three container-written files into a `RunResult`; blank/absent/garbage `rc` → sentinel exit code `_RC_ON_MISSING = 1`; `stdout`/`stderr` verbatim.
  - `_machine_name() -> str` — unique, hostname-valid `hp-<12 hex>`.
  - `_handler_lowers(booted_upper: Path, lowers: list[Path], base_lower: Path) -> list[Path]` — the §4 stack order `[booted_upper, *lowers, base_lower]` (used by the binds branch; validated here).
  - `BootedNspawnRunner(NspawnRunner)` — `prepare(lowers)` (overlay + boot, atomic), `run(argv, *, binds=None, setenv=None) -> RunResult`, `machine` property, `teardown()`. Inherits `rootfs`, `rootfs_upper`, `poweroff` from `NspawnRunner`.

**Tier:** the three helpers + their asserts are **tier1**; boot/run/teardown are **tier3**.

**Pure-logic materialized + validated at plan time** (scratch module + repo-`ruff.toml` check): **24 assertions pass, ruff-clean.**
- `_capture_files` — **11 asserts**: `"0"`→0; `"2"`→2; `"127"`→127; `""`→1; `"  \n"`→1; `"0\n"`→0; `"boot-failed"`→1; stdout/stderr verbatim; empty stdout preserved; `exit_code` is `int`.
- `_machine_name` — **6 asserts**: starts `hp-`; matches `^hp-[0-9a-f]{12}$`; `len==15`; `len<=64`; no leading/trailing hyphen; 2000 calls all unique.
- `_handler_lowers` — **7 asserts**: `[0]` is the booted upper; `[-1]` is base; middle preserves lower order; `":".join(...) == "/up:/l1:/l2:/base"`; `len==4`; empty-lowers → `[up, base]`; empty joined `"/up:/base"`.

- [ ] **Step 1: Write the failing tests**

`tests/runner/test_booted_pure.py` (tier1 — mirror the validated harness; 24 asserts):

```python
import re
from pathlib import Path

import pytest

from hashpass.runner.base import RunResult
from hashpass.runner.booted import _capture_files, _handler_lowers, _machine_name


@pytest.mark.tier1
def test_capture_files_parses_rc_and_passes_streams_verbatim():
    assert _capture_files("out\n", "err\n", "0") == RunResult("out\n", "err\n", 0)
    assert _capture_files("", "", "2").exit_code == 2      # noqa: PLR2004
    assert _capture_files("", "", "127").exit_code == 127  # noqa: PLR2004
    assert _capture_files("", "", "").exit_code == 1          # missing rc -> sentinel
    assert _capture_files("", "", "  \n").exit_code == 1      # blank rc -> sentinel
    assert _capture_files("", "", "0\n").exit_code == 0       # trailing newline stripped
    assert _capture_files("", "", "boot-failed").exit_code == 1  # garbage -> sentinel
    assert _capture_files("data", "warn", "0").stdout == "data"   # stdout verbatim
    assert _capture_files("data", "warn", "0").stderr == "warn"   # stderr verbatim
    assert _capture_files("", "", "3").stdout == ""              # empty stdout preserved
    assert isinstance(_capture_files("", "", "0").exit_code, int)


@pytest.mark.tier1
def test_machine_name_is_valid_and_unique():
    name = _machine_name()
    assert name.startswith("hp-")
    assert re.fullmatch(r"hp-[0-9a-f]{12}", name) is not None
    assert len(name) == 15                       # noqa: PLR2004
    assert len(name) <= 64                        # noqa: PLR2004
    assert name[0] != "-" and name[-1] != "-"
    assert len({_machine_name() for _ in range(2000)}) == 2000  # noqa: PLR2004


@pytest.mark.tier1
def test_handler_lowers_stack_order():
    up, l1, l2, base = Path("/up"), Path("/l1"), Path("/l2"), Path("/base")
    res = _handler_lowers(up, [l1, l2], base)
    assert res[0] == up                          # live booted upper on top
    assert res[-1] == base                        # base at bottom
    assert res[1:-1] == [l1, l2]                   # lowers order preserved
    assert ":".join(str(p) for p in res) == "/up:/l1:/l2:/base"
    assert len(res) == 4                          # noqa: PLR2004
    empty = _handler_lowers(up, [], base)
    assert empty == [up, base]
    assert ":".join(str(p) for p in empty) == "/up:/base"
```

`tests/runner/test_booted.py` (tier3 — boot + no-binds run):

```python
import pytest

from hashpass.image.base import build_base
from hashpass.runner.booted import BootedNspawnRunner


@pytest.mark.tier3
def test_booted_run_sees_real_systemd_and_persists(tmp_path, base_tar):
    # Booting needs a systemd-bearing base: build_base (Task 1) installs it.
    # The raw base_tar (trixie-slim) is NOT bootable -> always boot from a built base_dir.
    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = BootedNspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        # PID 1 is systemd, journald is up -> a real booted system (not a bare -D run).
        res = r.run(["sh", "-c", "ps -p 1 -o comm="])
        assert res.exit_code == 0
        assert "systemd" in res.stdout
        # exit code round-trips
        assert r.run(["sh", "-c", "exit 7"]).exit_code == 7  # noqa: PLR2004
        # writes persist in the booted overlay upperdir (absolute path -> /var/tmp round-trips)
        r.run(["sh", "-c", "echo persisted > /var/tmp/p.txt"])
        assert (r.rootfs_upper / "var/tmp/p.txt").read_text(encoding="utf-8").strip() == "persisted"
    finally:
        r.teardown()
```

- [ ] **Step 2: Run to verify they fail** — `python3 -m pytest tests/runner/test_booted_pure.py -v` → FAIL (`ModuleNotFoundError: hashpass.runner.booted`).

- [ ] **Step 3: Implement** — `src/hashpass/runner/booted.py` (complete; the `binds` branch is real, proven in Task 3):

```python
"""Booted systemd-nspawn runner: a real booted machine; commands via machinectl (mechanism §1-5)."""
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


def _handler_lowers(booted_upper: Path, lowers: list[Path], base_lower: Path) -> list[Path]:
    """Fresh /hp overlay stack (mechanism §4): live booted upper on top, same lowers, base bottom."""
    return [booted_upper, *lowers, base_lower]


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
        self._prepared_lowers = [Path(p) for p in lowers]   # remembered for the /hp handler stack
        self._hp = 0                                         # per-handler overlay counter
        try:
            self._boot()
        except Exception:            # noqa: BLE001 - boot failed: unmount + kill, then re-raise
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
                return
            time.sleep(1)
        msg = f"booted machine {self._machine!r} did not register within {_BOOT_TIMEOUT}s"
        raise RuntimeError(msg)

    def run(self, argv: list[str], *, binds: list[tuple[str, str]] | None = None,
            setenv: dict[str, str] | None = None) -> RunResult:
        """Run in the booted machine (no binds, §3) or on a fresh /hp-bound overlay (binds, §4)."""
        if binds:
            return self._run_handler(argv, binds, setenv or {})
        token = uuid4().hex
        rundir = f"/{_RUN_DIR}"
        # machinectl's PTY does not pipe stdout: redirect out/err/rc to overlay-backed files, then
        # read them host-side. `cd /` keeps cwd == '/' (parity with non-boot nspawn: relative writes).
        wrapped = (f"mkdir -p {rundir}; cd /; {shlex.join(argv)} "
                   f">{rundir}/{token}.out 2>{rundir}/{token}.err; "
                   f"printf %s $? >{rundir}/{token}.rc")
        subprocess.run(
            ["sudo", "machinectl", "shell", self._machine, "/bin/sh", "-c", wrapped],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )  # blocks until the command finishes
        host = self._mnt / _RUN_DIR
        return _capture_files(_read(host / f"{token}.out"),
                              _read(host / f"{token}.err"),
                              _read(host / f"{token}.rc"))

    def _run_handler(self, argv: list[str], binds: list[tuple[str, str]],
                     setenv: dict[str, str]) -> RunResult:
        """Run a /hp handler on a FRESH overlay stacking the LIVE booted upper + lowers + base (§4)."""
        self._hp += 1
        hp = self._wd / f"hp{self._hp}"
        upper, work, mnt = hp / "upper", hp / "work", hp / "mnt"
        for d in (upper, work, mnt):
            d.mkdir(parents=True, exist_ok=True)
        stack = _handler_lowers(self._upper, self._prepared_lowers, self._lower)
        overlay_mount(stack, upper, work, mnt, sudo=True)
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
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=_KILL_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._proc.kill()
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
```

- [ ] **Step 4: Run to verify they pass** — `python3 -m pytest tests/runner/test_booted_pure.py -v` → PASS (24 asserts across 3 tests). `python3 -m pytest tests/runner/test_booted.py -m tier3 -v` → PASS. `ruff check --config ruff.toml src/hashpass/runner/booted.py tests/runner/test_booted_pure.py tests/runner/test_booted.py` clean.

- [ ] **Step 5: Commit** — `git commit -m "feat(runner): BootedNspawnRunner — boot + machinectl run/capture + /hp fresh-overlay + robust teardown"`

Implementer notes:
- `machinectl shell <machine> /bin/sh -c "…"` runs as **root** in the machine (no `user@`), so it can write the `/…out|.err|.rc` files; `sudo` is only on the *host* `machinectl` binary (in scope). The in-container `mkdir`/`cd`/`printf`/`sh`/student command are the container's own binaries (unrestricted).
- The run-artifact dir is a **dot-dir at the overlay root** (`/.hp-run/…`) — overlay-backed so it round-trips to `<mnt>` host-side (unlike `/tmp`, which nspawn overlays with a private tmpfs), and hidden from a plain `ls /`. This is a deliberate one-token refinement of the proven `/<uuid>.out` for invisibility (see Open Items on accumulation/cleanup).
- `prepare()` is **atomic**: if boot times out it kills the half-booted process and unmounts before re-raising, so the two callers that construct-then-`prepare` a runner *outside* a try/finally (`taskbuild.factory`, `taskrun.run_task`) never leak a mount or a stale machine.

---

### Task 3: Validate the `/hp` handler fresh-overlay branch in a real booted machine + document limits

**Files:**
- Test: `tests/runner/test_booted_handler.py` (new, tier3)

**Interfaces:** none new — this task proves the `run(binds=…)` branch (mechanism §4) written in Task 2, against a **live booted** machine (the part that cannot be validated without real `systemd-nspawn`, hence its own task). It exercises the exact call `handler.run_handler` makes: `runner.run(argv, binds=[(hp, "/hp")], setenv=env)`.

**Tier:** tier3.

- [ ] **Step 1: Write the test** — `tests/runner/test_booted_handler.py`:

```python
import pytest

from hashpass.image.base import build_base
from hashpass.runner.booted import BootedNspawnRunner


@pytest.mark.tier3
def test_handler_overlay_sees_student_files_and_hp_without_busy_conflict(tmp_path, base_tar):
    hp = tmp_path / "hp"
    hp.mkdir()
    (hp / "token.txt").write_text("SECRET", encoding="utf-8")
    base = build_base(tmp_path / "base", from_tar=base_tar)   # bootable base (systemd installed)
    r = BootedNspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        # The student (in the booted machine) creates a file.
        r.run(["sh", "-c", "echo hi > /student.txt"])
        # A /hp handler runs on a SEPARATE fresh overlay (no busy-conflict with the booted mnt),
        # and sees BOTH the student's live file (stacked booted upper) AND the bound /hp.
        res = r.run(
            ["sh", "-c", "cat /student.txt; cat /hp/token.txt; printf ':%s' \"$HP_TRIES\""],
            binds=[(str(hp), "/hp")],
            setenv={"HP_TRIES": "4"},
        )
        assert res.exit_code == 0
        assert res.stdout == "hi\nSECRET:4"
        # A predicate handler returns the real exit code (acceptance basis for `check` stages).
        assert r.run(["sh", "-c", "grep -q hi /student.txt"], binds=[(str(hp), "/hp")]).exit_code == 0
        assert r.run(["sh", "-c", "grep -q NOPE /student.txt"], binds=[(str(hp), "/hp")]).exit_code != 0
        # The booted machine still runs (the handler did not disturb it).
        assert "systemd" in r.run(["sh", "-c", "ps -p 1 -o comm="]).stdout
    finally:
        r.teardown()
```

- [ ] **Step 2: Run to verify** — `python3 -m pytest tests/runner/test_booted_handler.py -m tier3 -v` → PASS. If it fails on a busy-conflict or an unreadable stacked upper, re-probe mechanism §4 before adjusting (the stack order and the fresh per-handler `upper`/`work`/`mnt` are load-bearing).

- [ ] **Step 3: Record the documented limits** — add a short module docstring block (or a `# Limits:` comment) in `runner/booted.py` capturing what the fresh-overlay handler **cannot** do, so callers/authors are not surprised:
  1. **FS-snapshot, not live PID.** The handler overlay stacks the booted upperdir as a *read-only lower*, so a handler sees the student's **files** but **not** the booted machine's live processes. Process/service *acceptance* must therefore be **observe/FS-based** (e.g. a stage command writes `pgrep … > /count.txt`; the file is graded) — a handler doing `pgrep` would see only its own transient ns. (Matches mechanism §4's stated limit.)
  2. **Racy if written concurrently.** The stacked upper is a live directory; the snapshot is consistent only because handlers run when the student is **idle between commands** (`TaskSession.feed` runs the student command to completion, *then* checks). Documented, accepted.
  3. **Handler rootfs writes are discarded.** The handler's writes to the container root land in the throwaway per-handler upperdir and do **not** reach the live booted student; only writes to the bound `/hp` persist (that is how `on_enter`/`on_pass`/`state.json` survive). Consequence: an `on_enter` that must **seed the live student filesystem** is unsupported — seed via the image (`run`/`copy` at build time) or via student/`solve` commands instead. (Checks, hints, and `/hp` state are unaffected.)

- [ ] **Step 4: Commit** — `git commit -m "test(runner): prove BootedNspawnRunner /hp handler overlay (student files + /hp, no busy-conflict) + document limits"`

---

### Task 4: Wire the booted runner — derive factory, student runner, bare-image run + CLI shell

**Files:**
- Modify: `src/hashpass/taskbuild.py` (derive `factory()` → `BootedNspawnRunner`)
- Modify: `src/hashpass/taskrun.py` (student runner → `BootedNspawnRunner`)
- Modify: `src/hashpass/build.py` (`run_image` → `BootedNspawnRunner`; **keep** `NspawnRunner` for `build`)
- Modify: `src/hashpass/cli.py` (`_run_image` interactive shell → `machinectl shell <machine> /bin/sh`)

**Interfaces:** all public signatures **unchanged** (`build_task`, `run_task`, `run_image`, `cmd_run`). `run_image` now returns a prepared **booted** runner (a `BootedNspawnRunner`, which *is* an `NspawnRunner`); it additionally exposes `.machine`.

**Tier:** tier3 (the effects are all in booted paths; no new tier1 logic).

**Why the derive factory must boot too:** acceptance is *derived* by running `solve` in the runner and canonicalizing, then the student's attempt is matched against it. If derivation ran non-boot but the student runs booted, the two environments differ (cwd, running services, `/proc`), risking a canonical that never matches. Booting **both** keeps derive/run parity. (This is the core reason `factory()` switches, not just the student.)

- [ ] **Step 1** — `taskbuild.py`: add `from hashpass.runner.booted import BootedNspawnRunner`; in the local `factory`, instantiate the booted runner:

```python
    def factory() -> BootedNspawnRunner:
        runner = BootedNspawnRunner(workdir / f"derive{next(counter)}", base_dir=base)
        runner.prepare(lowers)     # mounts the overlay AND boots the machine (atomic)
        return runner
```

The `_derive_stage`/`_selective_derive` params typed `Callable[[], NspawnRunner]` **stay valid** (a `BootedNspawnRunner` is an `NspawnRunner`; `run_stage` takes the `Runner` protocol). `runner.teardown()` in `_derive_stage`'s `finally` now powers off + unmounts. No other change; keep `passes` default and the `passes >= 2` guard.

- [ ] **Step 2** — `taskrun.py`: replace the student import/instantiation:

```python
from hashpass.runner.booted import BootedNspawnRunner
```
```python
    student = BootedNspawnRunner(workdir / "student", base_dir=base)
    student.prepare(lowers)        # boots once per session; each feed() runs via machinectl
```

`TaskSession.student` / `perform_action(runner=…)` keep their `NspawnRunner` hints (valid via subclassing). `TaskSession.feed` → `self.student.run(["sh","-c",command])` now runs in the booted machine (no binds → §3); `_accept`'s handler branch → `run_handler(self.student, …)` → `self.student.run(argv, binds=[(hp,"/hp")], …)` → §4 fresh overlay — **unchanged call sites**. Booting happens **once** at `run_task` (not per `feed`); the `except Exception: student.teardown()` guard already present still holds (and `prepare` is atomic, so a boot failure there cleans itself).

- [ ] **Step 3** — `build.py`: `run_image` returns a booted runner; **`build` is untouched** (its `run`/`copy` steps are inline non-boot `nspawn`, correct for build time):

```python
from hashpass.runner.booted import BootedNspawnRunner
```
```python
def run_image(ref: str, store: ImageStore, workdir: Path, *, base_tar: Path) -> BootedNspawnRunner:
    ...
    runner = BootedNspawnRunner(workdir / "run", base_dir=base)
    runner.prepare(lowers)
    return runner
```

- [ ] **Step 4** — `cli.py`: `_run_image` must **not** launch a second `nspawn -D runner.rootfs` (the booted machine holds `rootfs` exclusively → "busy"). Give the student a real shell **in the running system** via `machinectl shell`:

```python
def _run_image(env: Home, ref: str, store: ImageStore) -> int:
    """Open an interactive `/bin/sh` in the booted image machine (inherited stdio), then tear down."""
    runner = run_image(ref, store, env.work / "run", base_tar=env.base_tar)
    try:
        subprocess.run(["sudo", "machinectl", "shell", runner.machine, "/bin/sh"], check=False)
    finally:
        runner.teardown()
    return 0
```

- [ ] **Step 5: Run the directly-affected tier3 tests** — expect PASS (now booting, slower):
  - `python3 -m pytest tests/imagebuild/test_build.py::test_build_then_run_image_roundtrips -m tier3 -v` (run_image now boots; `runner.run(...)` returns via the §3 path).
  - `python3 -m pytest tests/test_cli_run.py tests/test_cli_e2e.py -m tier3 -v` (CLI task run now boots).
  `ruff check --config ruff.toml src/hashpass/taskbuild.py src/hashpass/taskrun.py src/hashpass/build.py src/hashpass/cli.py` clean.

- [ ] **Step 6: Commit** — `git commit -m "feat: run tasks/images in a booted machine (derive factory, student, run_image + CLI machinectl shell)"`

---

### Task 5: End-to-end validation + existing-tier3 impact sweep + perf/limits doc

**Files:**
- Possibly modify: any existing tier3 test that asserts a non-boot-specific detail (expected: **none** need logic changes — see the sweep below).
- Modify: `docs/superpowers/plans/2026-08-31-booted-runtime.md` self-review notes (this file) or a short note in the runner docstring — record the perf profile.

**Tier:** tier3.

**Existing-tier3 impact sweep** (verified against the merged tests; the guiding fact: `BootedNspawnRunner` honors the `Runner` protocol, so protocol-only callers pass **unchanged, only slower**):

| Test file | Path | Effect | Action |
|---|---|---|---|
| `tests/runner/test_nspawn.py` | constructs `NspawnRunner` directly (non-boot) | unaffected | none |
| `tests/test_handler.py` (tier3) | constructs `NspawnRunner` directly + `run_handler` | unaffected (non-boot handler still valid) | none |
| `tests/content/test_e2e_nspawn.py` | constructs `NspawnRunner`/`TmpdirRunner` directly | unaffected (relative `echo>hello.txt` relies on non-boot cwd=`/`, preserved) | none |
| `tests/image/test_base.py` | `build_base` | +systemd (Task 1) | bootability assert added in Task 1 |
| `tests/imagebuild/test_build.py` | `build` (non-boot) + `run_image` | `build` unaffected; `run_image` **now boots** | passes unchanged (Task 4 Step 5) |
| `tests/test_taskbuild.py` (tier3) | `build_task` → derive factory | **now boots** per pass | passes unchanged; keep `passes=2` |
| `tests/test_taskrun.py` (5 tier3) | `run_task` → student | **now boots**; derived + `check` + `on_enter`/`on_pass` + hint (all use **absolute** paths → cwd-agnostic) | passes unchanged |
| `tests/content/test_proc_audit.py` | `build_task` + `run_task` (process task) | **now boots** — flagship: `pgrep` against a real system | passes unchanged |
| `tests/test_cli_build.py` / `test_cli_run.py` / `test_cli_e2e.py` | `cmd_build`/`cmd_run` | **now boot** | pass unchanged |
| `tests/registry/test_local.py` (3 tier3) | registry push/pull (may build) | slower via `build_base` only | none |

- [ ] **Step 1: Full tier3 run** — `python3 -m pytest -m tier3 -v` (allow generous time; every derive pass boots ~2s and each `build_base` runs `apt-get`). Confirm **all pass**. The flagship is `tests/content/test_proc_audit.py` — a real `apt` install + `pgrep` process search now executed against a booted PID 1.

- [ ] **Step 2: Adapt only if red** — if any test fails, apply systematic-debugging (do not blanket-edit). Anticipated *non-failures*: absolute-path tasks are cwd-agnostic; `_capture_files` yields clean stdout/stderr/rc (cleaner than non-boot, which could carry nspawn chatter). If a test asserted a non-boot artifact, fix the **test**, not the runner. Keep `passes=2`.

- [ ] **Step 3: Record perf + limits** — confirm the "Perf reality" note (Global Constraints) and the three handler limits (Task 3 Step 3) are documented. Perf profile to state: **derivation** boots once per pass (`stages × passes` boots per build); **`run_task`/`run_image`** boot **once** per session; **`build_base`** runs `apt-get install` once per base-dir build (2–3× per full task build+run). Optional future optimization (out of scope): build one bootable base dir and reuse it across `build`/`build_task`/`run_task` instead of rebuilding per call.

- [ ] **Step 4: Commit** — `git commit -m "test: e2e booted-runtime sweep — existing tier3 green on booted machines; perf/limits documented"`

---

## Self-Review

**Goal coverage:**
- "Always booted" for **build-time derivation** (Task 4 factory), **student runtime** (Task 4 `run_task`), and **bare-image run** (Task 4 `run_image` + CLI) — every task now builds and runs in a booted machine. ✓
- Bootable base via the proven systemd install (Task 1). ✓
- Proven mechanism transcribed verbatim: boot `-b --register=yes -M` + `machinectl status` poll (§2, Task 2 `_boot`); `machinectl shell` + file-redirect + host-read (§3, Task 2 `run`); `/hp` fresh stacked overlay + non-boot `--bind`/`--setenv` (§4, Task 2 `_run_handler`, proven Task 3); `poweroff` + `overlay_umount` in `finally` (§5, Task 2 `teardown`). ✓
- Grading, `/hp` `HP_*` handler contract, hints, `on_enter`/`on_pass`, and invisibility preserved: `run_stage`/`capture`/`grade`/`TaskSession`/`run_handler` are **not modified** — only the instantiated class changes (protocol honored). ✓

**Sudo-scope respected:** every *host* `sudo` invocation is one of `systemd-nspawn`, `machinectl`, `mount`/`umount` (via `overlay_mount`/`overlay_umount`), `tar`, `rsync`. **No** `systemd-run`, **no** `nsenter`, **no** `sudo cat`, **no** `sudo rm` anywhere. Cleanup of run-artifacts is *not* done with host `rm` (the files are scratch on an ephemeral machine); `mkdir`/`printf` inside the wrapper are the container's own binaries via the already-authorized `machinectl shell` (not host sudo). ✓

**Pure-logic validated at plan time:** materialized in a scratch module + `ruff check --config ruff.toml` → **clean**; harness → **24 assertions pass** (`_capture_files` 11, `_machine_name` 6, `_handler_lowers` 7). These are the only tier1 units; all container behavior is tier3 (implementer runs `pytest -m tier3`). ✓

**Placeholder scan:** none. `runner/booted.py` is delivered **complete** in Task 2 (both `run` branches real); Task 3 adds a real tier3 test + limits doc, not stub code. Every code block is concrete; no `TODO`/`...`/`pass`-stub. ✓

**Type consistency:** `BootedNspawnRunner(NspawnRunner)` ⇒ is-a `NspawnRunner` ⇒ satisfies the `Runner` `Protocol`. Therefore `Callable[[], NspawnRunner]` factory hints (`taskbuild`), `TaskSession.student: NspawnRunner`, `perform_action(runner: NspawnRunner)`, and `run_handler(runner: NspawnRunner)` all remain valid **without edits**; `run_image`'s return is tightened to `BootedNspawnRunner` (a subtype, safe for its `.rootfs`/`.teardown()`/new `.machine` callers). `run()` keeps the exact `(argv, *, binds=None, setenv=None) -> RunResult` shape `handler.run_handler` and `run_stage` already call. ✓

**Existing-tier3 impact addressed:** full table in Task 5 — protocol-only callers pass unchanged (slower); the two behavioral touch-points (`run_image` now boots; CLI `_run_image` must switch to `machinectl shell` to avoid the busy-conflict) are handled in Task 4; direct-`NspawnRunner` tests stay non-boot and untouched; `image/test_base.py` gains a bootability assertion in Task 1. `passes=2` preserved. ✓

**Deviations / decisions beyond the brief (recorded):**
- **Subclassing** `NspawnRunner` (vs. a standalone class): maximizes reuse of `prepare`'s overlay mount, `rootfs`, `rootfs_upper` (exactly the booted upperdir §4 needs), and `poweroff`; the brief's "honoring the `Runner` protocol" is satisfied and downstream hints stay valid. The dormant `NspawnRunner.boot()` is **superseded** by `BootedNspawnRunner._boot()` (explicit proven `--register=yes` flags + timeout constant + auto unique name); leaving the unused parent `boot()` in place is harmless and out of scope to remove.
- **Run-artifacts in `/.hp-run/` (dot-dir at overlay root)** rather than the literal `/<uuid>.out`: same overlay round-trip guarantee (root of the overlay, not the `/tmp` private tmpfs), but hidden from a plain `ls /` so framework files do not leak into the student's view. A one-token, invisibility-preserving refinement of the proven §3 redirect.
- **`cd /` in the machinectl wrapper**: `machinectl shell` defaults cwd to `/root`, whereas non-boot `nspawn` runs at `/`; `cd /` restores parity so relative-path commands (noise, any relative `solve`) behave identically across derive and run (both booted) and match the historical non-boot semantics.
- **`prepare()` is atomic** (self-cleans on boot failure): required because two callers construct-then-`prepare` a runner *outside* a try/finally — without it a boot timeout would leak the mount + a stale machine.

**Biggest open question / risk (tier3):** the §4 handler overlay stacks the **live** booted upperdir as a read-only lower — proven in a live probe, but the overlayfs "upperdir-of-one-mount-as-lowerdir-of-another" interaction is the least conventional mechanism here; Task 3 exists to prove it in CI-for-tier3 before the wiring depends on it. Its documented consequence — **handlers see the student's files but not live PIDs, and handler rootfs writes are discarded** — means process/service **acceptance must be observe/FS-based** and an `on_enter` cannot seed the live student filesystem (seed via the image or student commands). This is consistent with the spec's acceptance model but is the sharpest behavioral edge of "always booted," so it is documented in three places (Task 3 Step 3, the runner docstring, and here).
