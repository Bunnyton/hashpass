"""
Run the x86_64 task images on another architecture through qemu (binfmt_misc).

The base image and every task are built for x86_64. On an ARM machine systemd-nspawn then fails
with «execv(/usr/lib/systemd/systemd, …) failed: Exec format error» (a student, 2026-10-13). With
`qemu-user-static` the kernel runs x86 programs through the emulator -- inside the container too,
when the binfmt entry carries the F (fix-binary) flag. hashpass installs it at start when needed
(user: «hashpass пусть устанавливает при запуске, если нужно»).
"""
import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

_BINFMT_DIR = Path("/proc/sys/fs/binfmt_misc")
_BINFMT = _BINFMT_DIR / "qemu-x86_64"
# Rosetta first: a Linux VM in UTM on a Mac (Ubuntu arm64, 2026-10-23) runs x86 through Apple's
# translator far more reliably than through qemu-user, where man and some services crashed.
_EMULATORS = ("rosetta", "qemu-x86_64")
_NATIVE = ("x86_64", "amd64")
# Newer releases (Debian 13, recent Ubuntu) split qemu-user-static into qemu-user (static now) +
# qemu-user-binfmt; older ones still have it. A student got «Для пакета «qemu-user-static» не найден
# кандидат на установку» -- so pick the set this system can actually install.
_PACKAGE_SETS = (("qemu-user", "qemu-user-binfmt"), ("qemu-user-static", "binfmt-support"))


def binfmt_ready(entry: Path | None = None, *, binfmt_dir: Path = _BINFMT_DIR) -> bool:
    """Whether the kernel runs x86_64 programs (Rosetta or qemu), also inside a container (enabled + F)."""
    if entry is None:
        return x86_emulator(binfmt_dir) is not None
    try:
        lines = entry.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    flags = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("flags:")), "")
    return bool(lines) and lines[0].strip() == "enabled" and "F" in flags


def x86_emulator(binfmt_dir: Path = _BINFMT_DIR) -> Path | None:
    """Return the binfmt entry that runs x86_64 here, Rosetta first; None when there is none."""
    return next((binfmt_dir / name for name in _EMULATORS if binfmt_ready(binfmt_dir / name)), None)


def emulator_description(binfmt_dir: Path = _BINFMT_DIR) -> str:
    """Name the x86 emulator, its program and its version (for the emulation report)."""
    entry = x86_emulator(binfmt_dir)
    if entry is None:
        return "эмулятор x86 не найден"
    lines = entry.read_text(encoding="utf-8").splitlines()
    program = next((ln.split(None, 1)[1] for ln in lines if ln.startswith("interpreter ")), "")
    said = f"{entry.name} ({program})"
    if entry.name == "rosetta" or not program:
        return said
    try:
        out = subprocess.run([program, "--version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return said
    first = (out.stdout or out.stderr).strip().splitlines()
    return f"{said}: {first[0]}" if first else said


def _installable(pkgs: tuple[str, ...], run: Callable[..., object]) -> bool:
    """Whether apt has an install candidate for every package in `pkgs` (`apt-cache policy`)."""
    res = run(["apt-cache", "policy", *pkgs], capture_output=True, text=True, check=False)
    out = str(getattr(res, "stdout", "") or "")
    found = {}
    current = None
    for line in out.splitlines():
        if line and not line.startswith(" ") and line.endswith(":"):
            current = line[:-1]
        elif current and line.strip().startswith("Candidate:"):
            found[current] = line.split(":", 1)[1].strip() not in ("", "(none)")
    return all(found.get(p, False) for p in pkgs)


def _package_set(run: Callable[..., object]) -> tuple[str, ...] | None:
    return next((s for s in _PACKAGE_SETS if _installable(s, run)), None)


def ensure_x86_emulation(write: Callable[[str], object], *,
                         machine: Callable[[], str] = platform.machine,
                         ready: Callable[[], bool] = binfmt_ready,
                         run: Callable[..., object] = subprocess.run,
                         has_apt: Callable[[], bool] = lambda: shutil.which("apt-get") is not None,
                         ) -> bool:
    """
    Make sure x86_64 task images can boot here; install qemu-user-static if it is missing.

    Returns whether they can. An x86_64 machine needs nothing. Never raises: on failure it says
    what to do, and the catalog still opens.
    """
    arch = machine()
    if arch in _NATIVE or ready():
        return True
    write(f"Задания собраны для x86_64, а у этого компьютера процессор {arch}. Чтобы они "
          "запускались, нужен эмулятор x86 (qemu-user-static).\n")
    if not has_apt():
        write("\x1b[33m⚠ поставьте эмулятор x86 средствами своей системы (пакеты qemu-user и "
              "qemu-user-binfmt, в старых — qemu-user-static) и перезапустите hashpass\x1b[0m\n")
        return False
    write("Ставлю его (один раз):\n")
    pkgs = _package_set(run)
    if pkgs is None:                                     # stale package lists: refresh once
        run(["sudo", "apt-get", "update"], check=False)
        pkgs = _package_set(run) or _PACKAGE_SETS[-1]
    run(["sudo", "apt-get", "install", "-y", *pkgs], check=False)
    if not ready():                                      # registered, but not loaded yet
        run(["sudo", "systemctl", "restart", "systemd-binfmt"], check=False)
    if ready():
        write("\x1b[32m✓ эмулятор x86 готов — задания запустятся (чуть медленнее, чем на x86)\x1b[0m\n")
        return True
    write("\x1b[33m⚠ не удалось включить эмулятор x86: задания не запустятся. Попробуйте "
          "`sudo apt-get install qemu-user qemu-user-binfmt` и перезагрузку.\x1b[0m\n")
    return False


_EMULATED = Path(__file__).with_name("emulated")
_REPORT = "var/log/hp-emulated-report.txt"


def emulated(machine: Callable[[], str] = platform.machine) -> bool:
    """Whether the x86_64 images run here through qemu (HASHPASS_FORCE_EMULATED=1: act as if)."""
    return machine() not in _NATIVE or os.environ.get("HASHPASS_FORCE_EMULATED") == "1"


_NO_MAN_SECCOMP = "MAN_DISABLE_SECCOMP=1"


def _man_without_seccomp(rootfs: Path) -> list[str]:
    """
    Bind a console rc and a `man` wrapper that switch man-db's sandbox off.

    arm64 (2026-10-23): `man man` -- «Segmentation fault». man-db runs its helpers under a seccomp
    filter, and qemu-user has no seccomp; MAN_DISABLE_SECCOMP=1 is man-db's own switch. Every
    console shell (and `su -`, `sudo -i`) reads /etc/hp-bashrc; plain `sudo man` resets the
    environment (and this sudo has no pam_env), but its secure_path finds /usr/local/bin/man
    first. The copies live next to the rootfs, on the host side.
    """
    out_dir = Path(rootfs).parent
    args = []
    try:
        rc = (Path(rootfs) / "etc" / "hp-bashrc").read_text(encoding="utf-8")
    except OSError:
        rc = None
    try:
        if rc is not None:
            (out_dir / "hp-emulated-bashrc").write_text(f"export {_NO_MAN_SECCOMP}\n{rc}", encoding="utf-8")
            args.append(f"--bind-ro={out_dir / 'hp-emulated-bashrc'}:/etc/hp-bashrc")
        wrapper = out_dir / "hp-emulated-man"
        wrapper.write_text(f'#!/bin/sh\n# hashpass under qemu: man-db without seccomp\n'
                           f'{_NO_MAN_SECCOMP} exec /usr/bin/man "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        args.append(f"--bind-ro={wrapper}:/usr/local/bin/man")
    except OSError:
        return []                                     # no place for the copies: man stays as is
    return args


def nspawn_emulation_args(machine: Callable[[], str] = platform.machine,
                          rootfs: Path | None = None) -> list[str]:
    """
    Extra `systemd-nspawn -b` arguments for booting an x86_64 image under qemu-user.

    A MacBook (ARM, 2026-10-23): «запускается, но часть сервисов failed». qemu-user gives no
    seccomp (systemd: status=228/SECCOMP) and not every namespace set-up (226/NAMESPACE), which
    service sandboxes need. So: `SYSTEMD_SECCOMP=0` for systemd, a drop-in for EVERY service
    relaxing its sandbox (as runtime 44 did for logind), a unit writing what still failed
    to /var/log for the host to show, and -- given the `rootfs` -- man without its seccomp
    sandbox. Nothing changes on x86, and the base image stays as is.
    """
    if not emulated(machine):
        return []
    dropin = _EMULATED / "hp-emulated.conf"
    report = _EMULATED / "hp-emulated-report.service"
    wants = _EMULATED / "hp-emulated-report.conf"
    script = _EMULATED / "hp-emulated-report.sh"
    return ["--setenv=SYSTEMD_SECCOMP=0",
            f"--bind-ro={dropin}:/etc/systemd/system/service.d/hp-emulated.conf",
            f"--bind-ro={report}:/etc/systemd/system/hp-emulated-report.service",
            f"--bind-ro={wants}:/etc/systemd/system/multi-user.target.d/hp-emulated-report.conf",
            f"--bind-ro={script}:/usr/local/lib/hp-emulated-report.sh",
            *(_man_without_seccomp(rootfs) if rootfs is not None else [])]


def failed_units(rootfs: Path) -> list[str]:
    """Return the services the emulated console reported as failed (empty: none, or no report)."""
    try:
        text = (Path(rootfs) / _REPORT).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    section, out = "", []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section == "failed units" and line.strip():
            out.append(line.split()[0])
    return out
