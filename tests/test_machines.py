"""
Tier1: any number of hashpass runs on one machine.

User 2026-10-24: «неограниченное количество запусков на одном устройстве — для серверов».

Every run started by terminating EVERY `hp-*` machine («assumes one hashpass run at a time»), so a
second student's start killed the first one's console; checks and builds booted `-D …/mnt` without
`-M`, so two at once clashed on the machine name `mnt`.
"""
import os
import re

import pytest

from hashpass import machines


@pytest.mark.tier1
def test_a_machine_name_carries_the_process_that_owns_it() -> None:
    name = machines.machine_name()
    assert re.fullmatch(rf"hp-{os.getpid()}-[0-9a-f]{{8}}", name)
    assert len(name) <= 64  # noqa: PLR2004
    assert len({machines.machine_name() for _ in range(2000)}) == 2000  # noqa: PLR2004
    assert machines.owner(name) == os.getpid()
    assert machines.owner("hp-0123456789ab") is None          # an older client's name: owner unknown
    assert machines.owner("mnt") is None


@pytest.mark.tier1
def test_only_machines_whose_hashpass_is_gone_are_reaped(monkeypatch) -> None:
    alive, dead = os.getpid(), 999_999_999
    listing = (f"hp-{alive}-aaaaaaaa container systemd-nspawn debian 13 -\n"
               f"hp-{dead}-bbbbbbbb container systemd-nspawn debian 13 -\n"
               "hp-0123456789ab container systemd-nspawn debian 13 -\n"
               "other container systemd-nspawn debian 13 -\n")
    terminated: list[str] = []
    monkeypatch.setattr(machines, "_list", lambda: listing)
    monkeypatch.setattr(machines, "_terminate", terminated.append)
    machines.reap_orphans()
    assert terminated == [f"hp-{dead}-bbbbbbbb"]


@pytest.mark.tier1
def test_another_users_hashpass_counts_as_alive(monkeypatch) -> None:
    """kill(pid, 0) on someone else's process says EPERM: it runs -- leave its machine alone."""
    def no_permission(_pid: int, _sig: int) -> None:
        raise PermissionError
    monkeypatch.setattr(machines.os, "kill", no_permission)
    assert machines.alive(4242) is True


@pytest.mark.tier1
def test_every_nspawn_call_names_its_machine() -> None:
    """No `systemd-nspawn` without `-M`: an unnamed one is called after its directory (`mnt`)."""
    from pathlib import Path  # noqa: PLC0415
    src = Path(machines.__file__).parent
    for path in [*src.glob("*.py"), *src.glob("runner/*.py")]:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'\["sudo", "systemd-nspawn",[^\]]*', text):
            call = text[m.start():m.start() + 400]
            assert '"-M"' in call, f"{path.name}: systemd-nspawn without -M"


@pytest.mark.tier1
def test_a_console_that_would_not_fit_says_which_limit_and_how_to_raise_it(monkeypatch) -> None:
    """At the inotify limit the next console's systemd dies cryptically; say it plainly instead."""
    monkeypatch.setattr(machines, "_inotify_limit", lambda: 128)
    monkeypatch.setattr(machines, "running", lambda: 30)
    msg = machines.no_room()
    assert msg is not None and "fs.inotify.max_user_instances" in msg and "sudo sysctl" in msg
    monkeypatch.setattr(machines, "running", lambda: 10)
    assert machines.no_room() is None
    monkeypatch.setattr(machines, "_inotify_limit", lambda: 8192)
    monkeypatch.setattr(machines, "running", lambda: 500)
    assert machines.no_room() is None
