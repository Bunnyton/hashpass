"""
Names of hashpass's containers, so that any number of runs share one machine (a server).

A name is `hp-<pid>-<random>`: the pid of the hashpass process that booted it. Before a boot,
machines whose hashpass is gone (Ctrl-C, a closed terminal) are terminated -- they hold ptys --
and every other one is left alone: it is someone's live console (user 2026-10-24: «неограниченное
количество запусков на одном устройстве — для серверов»).
"""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
import uuid
from pathlib import Path

PREFIX = "hp-"
_OWNED = re.compile(r"hp-(\d+)-[0-9a-f]+")


def machine_name() -> str:
    """Return a unique, hostname-valid machine name owned by this process."""
    return f"{PREFIX}{os.getpid()}-{uuid.uuid4().hex[:8]}"


def owner(name: str) -> int | None:
    """Return the pid of the hashpass that booted machine `name`; None if the name does not say."""
    m = _OWNED.fullmatch(name)
    return int(m.group(1)) if m else None


def alive(pid: int) -> bool:
    """Whether process `pid` exists (another user's process counts: kill() says EPERM)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _list() -> str:
    return subprocess.run(["machinectl", "list", "--no-legend"],
                          capture_output=True, text=True, check=False).stdout


def _terminate(name: str) -> None:
    subprocess.run(["sudo", "machinectl", "terminate", name], check=False, capture_output=True)


def reap_orphans() -> None:
    """
    Terminate the machines whose hashpass process is gone, reclaiming their ptys.

    A leaked machine holds ptys against kernel.pty.max; enough of them and a fresh boot fails
    with «No space left on device». A machine of a live hashpass -- this user's other terminal
    or another user's -- is never touched; nor is a name without an owner (an older client).
    """
    with contextlib.suppress(Exception):
        for line in _list().splitlines():
            parts = line.split()
            pid = owner(parts[0]) if parts else None
            if pid is not None and not alive(pid):
                _terminate(parts[0])


# Each console's systemd (PID 1, journald, logind…) takes about this many inotify instances, all
# counted against root's fs.inotify.max_user_instances -- 128 by default: the 31st console on one
# machine died «Failed to create control group inotify object: Too many open files» (2026-10-24).
INOTIFY_PER_CONSOLE = 4
_RESERVE = 8                    # the host's own root daemons hold some too
RAISE = ("sudo sysctl -w fs.inotify.max_user_instances=8192 fs.inotify.max_user_watches=1048576")


def _inotify_limit() -> int:
    try:
        return int(Path("/proc/sys/fs/inotify/max_user_instances").read_text())
    except (OSError, ValueError):
        return 0


def running() -> int:
    """Return how many hashpass consoles and checks run on this machine now."""
    with contextlib.suppress(Exception):
        return sum(1 for line in _list().splitlines() if line.startswith(PREFIX))
    return 0


def no_room() -> str | None:
    """Return why one more console would not boot (the inotify limit), or None if it fits."""
    limit = _inotify_limit()
    if not limit:
        return None
    fits = max(1, (limit - _RESERVE) // INOTIFY_PER_CONSOLE)
    if running() < fits:
        return None
    return (f"на этой машине уже {running()} консолей hashpass — больше не поместится: у ядра "
            f"fs.inotify.max_user_instances = {limit}, а каждой консоли нужно ~{INOTIFY_PER_CONSOLE}.\n"
            f"Поднимите лимит (администратор машины):  {RAISE}\n"
            f"Навсегда — то же в /etc/sysctl.d/60-hashpass.conf (это делает установка hashpass).")
