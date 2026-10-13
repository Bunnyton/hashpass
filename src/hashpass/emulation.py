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
_PACKAGES = ("qemu-user-static", "binfmt-support")


def binfmt_ready(entry: Path = _BINFMT) -> bool:
    """Whether the kernel runs x86_64 programs via qemu, also inside a container (enabled + F)."""
    try:
        lines = entry.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    flags = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("flags:")), "")
    return bool(lines) and lines[0].strip() == "enabled" and "F" in flags


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
        write("\x1b[33m⚠ поставьте пакет qemu-user-static (и binfmt-support) средствами своей "
              "системы и перезапустите hashpass\x1b[0m\n")
        return False
    write("Ставлю его (один раз):\n")
    run(["sudo", "apt-get", "install", "-y", *_PACKAGES], check=False)
    if not ready():                                      # registered, but not loaded yet
        run(["sudo", "systemctl", "restart", "systemd-binfmt"], check=False)
    if ready():
        write("\x1b[32m✓ эмулятор x86 готов — задания запустятся (чуть медленнее, чем на x86)\x1b[0m\n")
        return True
    write("\x1b[33m⚠ не удалось включить эмулятор x86: задания не запустятся. Попробуйте "
          "`sudo apt-get install qemu-user-static binfmt-support` и перезагрузку.\x1b[0m\n")
    return False
