"""
Run the x86_64 task images on another architecture through qemu (binfmt_misc).

The base image and every task are built for x86_64. On an ARM machine systemd-nspawn then fails
with «execv(/usr/lib/systemd/systemd, …) failed: Exec format error» (a student, 2026-10-13). With
`qemu-user-static` the kernel runs x86 programs through the emulator -- inside the container too,
when the binfmt entry carries the F (fix-binary) flag. hashpass installs it at start when needed
(user: «hashpass пусть устанавливает при запуске, если нужно»).
"""
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

_BINFMT = Path("/proc/sys/fs/binfmt_misc/qemu-x86_64")
_NATIVE = ("x86_64", "amd64")
# Newer releases (Debian 13, recent Ubuntu) split qemu-user-static into qemu-user (static now) +
# qemu-user-binfmt; older ones still have it. A student got «Для пакета «qemu-user-static» не найден
# кандидат на установку» -- so pick the set this system can actually install.
_PACKAGE_SETS = (("qemu-user", "qemu-user-binfmt"), ("qemu-user-static", "binfmt-support"))


def binfmt_ready(entry: Path = _BINFMT) -> bool:
    """Whether the kernel runs x86_64 programs via qemu, also inside a container (enabled + F)."""
    try:
        lines = entry.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    flags = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("flags:")), "")
    return bool(lines) and lines[0].strip() == "enabled" and "F" in flags


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
