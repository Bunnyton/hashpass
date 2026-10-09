"""
Get sudo up front, in the plain terminal, before anything runs `sudo` with captured output.

hashpass calls `sudo tar/rsync/systemd-nspawn` with captured output -- in the TUI also from a
background download thread. Without a cached sudo credential the password prompt then lands
under the full-screen UI (or nowhere) and the run just hangs. So the student CLI asks ONCE at
start (`sudo -v`, a normal visible prompt) and keeps the credential fresh while it runs.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable

_KEEPALIVE = 60.0      # seconds between `sudo -n -v` refreshes (sudo's default timeout is 15 min)
_PROBES = (["sudo", "-n", "systemd-nspawn", "--version"],   # scoped NOPASSWD covers this one
           ["sudo", "-n", "true"])                          # full NOPASSWD / a cached credential
_started = threading.Event()


def _quiet(argv: list[str]) -> bool:
    return subprocess.run(argv, capture_output=True, check=False).returncode == 0


def _keepalive() -> None:
    while True:
        time.sleep(_KEEPALIVE)
        _quiet(["sudo", "-n", "-v"])


def _start_keepalive() -> None:
    if not _started.is_set():
        _started.set()
        threading.Thread(target=_keepalive, daemon=True, name="sudo-keepalive").start()


def ensure_sudo(write: Callable[[str], object]) -> bool:
    """
    Make sure `sudo` works without a prompt from now on; return whether it does.

    Root, or a passwordless rule -> True at once. Otherwise, on a terminal, ask for the password
    with a visible `sudo -v`. Never raises: on failure it explains and the caller carries on
    (the catalog still works; a run will fail with sudo's own message).
    """
    if os.geteuid() == 0:
        return True
    if shutil.which("sudo") is None:
        write("\x1b[33m⚠ нет sudo — задания запускаются в контейнере systemd-nspawn, "
              "ему нужны права root\x1b[0m\n")
        return False
    if any(_quiet(p) for p in _PROBES):
        _start_keepalive()
        return True
    if not sys.stdin.isatty():
        write("\x1b[33m⚠ hashpass нужен sudo без пароля (или запустите его в терминале — "
              "он спросит пароль)\x1b[0m\n")
        return False
    write("hashpass запускает задания в контейнере (systemd-nspawn), для этого нужен sudo.\n")
    ok = subprocess.run(["sudo", "-v", "-p", "[sudo] пароль для %u: "], check=False).returncode == 0
    if not ok:
        write("\x1b[33m⚠ sudo не получен — каталог открою, но задания запускаться не будут\x1b[0m\n")
        return False
    _start_keepalive()
    return True
