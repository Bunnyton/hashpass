"""
Run a task's console in an AppArmor policy namespace of its own, so the host's profiles stay out.

AppArmor attaches a profile to a program by its PATH, and the path inside a container looks the
same: Ubuntu's profile for /usr/bin/man (man-db) then confines the console's man too, and under
x86 emulation its man_groff/man_filter children may not map qemu-x86_64 -- troff, tbl and col
segfault (Ubuntu arm64 in UTM, hp-diag 2026-11-04). LXD does the same thing for its containers:
a namespace holds no profiles of the host, so nothing attaches inside it.

User 2026-11-04: «погнали вторым способом пробовать» -- HASHPASS_AA_ISOLATE=1 turns it on, =0 off;
once proven live (DEFAULT_ON) it is on by default under emulation. The way is proven by a probe before a console
relies on it; when the probe fails, the console starts as before.
"""
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

NAMESPACE = "hashpass"
# Off until a whole console has booted in the namespace on a real machine (2026-11-04): then on
# by default under emulation.
DEFAULT_ON = False
_ENABLED = Path("/sys/module/apparmor/parameters/enabled")
_NAMESPACES = Path("/sys/kernel/security/apparmor/policy/namespaces")


def _quiet(argv: list[str]) -> bool:
    try:
        return subprocess.run(argv, capture_output=True, check=False, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _emulated() -> bool:
    from hashpass.emulation import emulated  # noqa: PLC0415  (emulation imports a lot)
    return emulated()


def prefix(*, emulated: bool | None = None, run: Callable[[list[str]], bool] = _quiet,
           which: Callable[[str], str | None] = shutil.which,
           enabled: Path = _ENABLED, namespaces: Path = _NAMESPACES) -> list[str]:
    """`aa-exec … --` to put before systemd-nspawn (after sudo), or [] -- the console as before."""
    asked = os.environ.get("HASHPASS_AA_ISOLATE", "")
    default = DEFAULT_ON and (_emulated() if emulated is None else emulated)
    if asked == "0" or (asked != "1" and not default):
        return []
    try:
        on = enabled.read_text(encoding="utf-8").strip() == "Y"
    except OSError:
        on = False
    if not on or not namespaces.is_dir() or not which("aa-exec"):
        return []
    argv = ["aa-exec", "-n", NAMESPACE, "-p", "unconfined", "--"]
    run(["sudo", "-n", "mkdir", "-p", str(namespaces / NAMESPACE)])
    return argv if run(["sudo", "-n", *argv, "true"]) else []


def nspawn_cmd() -> list[str]:
    """How to start systemd-nspawn for a console or a lab machine: sudo [aa-exec …] systemd-nspawn."""
    return ["sudo", *prefix(), "systemd-nspawn"]
