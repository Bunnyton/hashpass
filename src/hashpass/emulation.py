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
import sys
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


_VIRTIOFS_DIR = Path("/sys/fs/virtiofs")
_DMI_DIR = Path("/sys/class/dmi/id")
# Rosetta for Linux takes x86_64 ELF binaries (F: also inside containers) -- as the installer does
ROSETTA_BINFMT = (r":rosetta:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x3e\x00:"
                  r"\xff\xff\xff\xff\xff\xfe\xfe\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:"
                  r"/media/rosetta/rosetta:CF")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _rosetta_shared(virtiofs_dir: Path) -> bool:
    """Whether the VM shares Apple's translator (UTM «Enable Rosetta»: the virtiofs tag `rosetta`)."""
    return any(_read(t) == "rosetta" for t in virtiofs_dir.glob("*/tag"))


def _ask_tty(question: str) -> str:
    if not sys.stdin.isatty():
        return ""
    try:
        return input(question)
    except EOFError:
        return ""


def rosetta_advice(write: Callable[[str], object], *,  # noqa: PLR0913, PLR0911
                   machine: Callable[[], str] = platform.machine,
                   ask: Callable[[str], str] = _ask_tty,
                   run: Callable[..., object] = subprocess.run,
                   virtiofs_dir: Path = _VIRTIOFS_DIR, binfmt_dir: Path = _BINFMT_DIR,
                   dmi_dir: Path = _DMI_DIR) -> bool:
    """
    At start, on a Mac VM still running the tasks through qemu: say how Rosetta helps; hook it up.

    User 2026-11-05: «рекомендации по включению rosetta при apple вынеси при запуске hashpass».
    Rosetta shared but idle -> offer to hook it up now (with consent); a Mac VM without it -> how
    to turn it on in UTM. Native x86, Rosetta already working, or not a Mac -- silence. Returns
    whether Rosetta got hooked up just now.
    """
    if machine() in _NATIVE or binfmt_ready(binfmt_dir / "rosetta"):
        return False
    shared = _rosetta_shared(virtiofs_dir)
    vendor = _read(dmi_dir / "sys_vendor")
    if not shared and not any(v in vendor for v in ("Apple", "QEMU")):
        return False
    if not shared:
        write("\x1b[33m💡 Задания сейчас идут через эмулятор qemu. Если это виртуалка на Mac, через Rosetta "
              "они пойдут быстрее и надёжнее:\x1b[0m\n"
              "   UTM → новая машина «Virtualize» → «Linux», отметьте «Use Apple Virtualization» и\n"
              "   «Enable Rosetta (x86_64 Emulation)», поставьте в неё Ubuntu arm64 и hashpass —\n"
              "   установщик сам подключит Rosetta.\n")
        return False
    answer = ask("💡 Виртуалке доступна Rosetta (транслятор x86 от Apple), а задания идут через qemu. "
                 "Подключить Rosetta? Понадобится sudo. [Д/н] ").strip().lower()
    if answer in ("н", "n", "нет", "no"):
        return False
    if not answer:
        write("   подключить потом: перезапустите hashpass в терминале и ответьте «д»\n")
        return False
    run(["sudo", "mkdir", "-p", "/media/rosetta"], check=False)
    run(["sudo", "mount", "-t", "virtiofs", "rosetta", "/media/rosetta"], check=False)
    fstab = ("grep -qs '^rosetta[[:space:]]' /etc/fstab || "
             "echo 'rosetta /media/rosetta virtiofs ro,nofail 0 0' >> /etc/fstab")
    run(["sudo", "sh", "-c", fstab], check=False)
    run(["sudo", "tee", "/etc/binfmt.d/rosetta.conf"], input=ROSETTA_BINFMT + "\n", text=True,
        capture_output=True, check=False)
    run(["sudo", "systemctl", "restart", "systemd-binfmt"], check=False)
    if binfmt_ready(binfmt_dir / "rosetta"):
        write("\x1b[32m✓ Rosetta подключена: задания x86 пойдут через неё\x1b[0m\n")
        return True
    write("\x1b[33m⚠ Rosetta не включилась — задания пойдут через qemu, как раньше\x1b[0m\n")
    return False


_EMULATED = Path(__file__).with_name("emulated")
_REPORT = "var/log/hp-emulated-report.txt"


def emulated(machine: Callable[[], str] = platform.machine) -> bool:
    """Whether the x86_64 images run here through qemu (HASHPASS_FORCE_EMULATED=1: act as if)."""
    return machine() not in _NATIVE or os.environ.get("HASHPASS_FORCE_EMULATED") == "1"


_NO_MAN_SECCOMP = "MAN_DISABLE_SECCOMP=1"
_LOADER = "/lib64/ld-linux-x86-64.so.2"      # the x86_64 images' dynamic loader


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
        # through the loader: the HOST's AppArmor profile for /usr/bin/man (Ubuntu's man-db) would
        # attach to «/usr/bin/man» and send troff/tbl/col into man_groff/man_filter, which may not
        # map qemu-x86_64 -- they segfault (arm64 Ubuntu, hp-diag 2026-11-04)
        wrapper.write_text(f'#!/bin/sh\n# hashpass under qemu: man-db without seccomp and the host man profile\n'
                           f'{_NO_MAN_SECCOMP} exec {_LOADER} /usr/bin/man "$@"\n', encoding="utf-8")
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
