"""
A lab's live network: netns holders, the wiring, the nodes' boots (spec 2026-11-02 §6).

Nothing touches the host's network: every machine gets a network namespace held by a tiny
`hpn-` machine (`systemd-nspawn --private-network --read-only` on the base) which is also that
machine's grade relay -- `systemd-socket-activate -l 127.0.0.1:<port>` + `systemd-socket-proxyd`
to a host unix socket, so the console's hooks reach `127.0.0.1:$HP_PORT` as in a plain task.
One more holder is the switch: its netns gets a bridge per network and the veth pairs
(wire.py). Nodes then boot into their ready namespaces; the console joins its own.
"""
from __future__ import annotations

import base64
import contextlib
import subprocess
import time
from typing import TYPE_CHECKING

from hashpass import machines
from hashpass.emulation import nspawn_emulation_args
from hashpass.lab.config import PORT_UNIT, hosts_text, port_unit
from hashpass.lab.wire import wire_script

if TYPE_CHECKING:
    from pathlib import Path

    from hashpass.lab.model import Lab
    from hashpass.runner.nspawn import NspawnRunner

_GRADE_IN = "/run/hp-grade"          # where a holder sees the host's socket directory
_SOCKET_ACTIVATE = "/usr/bin/systemd-socket-activate"
_PROXYD = "/usr/lib/systemd/systemd-socket-proxyd"
_LEADER_WAIT = 20.0                  # seconds for a holder to come up
_POLL = 0.1


def _leader(name: str) -> int | None:
    out = subprocess.run(["machinectl", "show", "-p", "Leader", "--value", name],
                         capture_output=True, text=True, check=False).stdout.strip()
    return int(out) if out.isdigit() and out != "0" else None


def _write_files(runner: NspawnRunner, files: dict[str, str], *, root_owned: bool) -> None:
    """Write files into a not-yet-booted machine (non-boot nspawn on its mount)."""
    parts = ["set -e"]
    if root_owned:
        # the overlay's root dir is made by the host user (uid 1000): systemd and sshd want `/` root's
        parts.append("chown 0:0 /")
    for path, text in files.items():
        b64 = base64.b64encode(text.encode()).decode()
        parts += [f'mkdir -p "$(dirname {path})"', f"echo {b64} | base64 -d > {path}"]
    res = runner.run(["sh", "-c", "\n".join(parts)])
    if res.exit_code != 0:
        msg = f"не удалось подготовить машину стенда: {res.stderr.strip()}"
        raise RuntimeError(msg)


class LabRuntime:
    """The live lab of one task session: start before the console, stop after it."""

    def __init__(self, lab: Lab, hosts: bool, console: NspawnRunner,  # noqa: FBT001, PLR0913, PLR0917
                 nodes: dict[str, NspawnRunner], base: Path, sock_dir: Path) -> None:
        """Bind the lab config to its prepared runners; `sock_dir` will hold the grade sockets."""
        self.lab, self.hosts, self.console, self.nodes = lab, hosts, console, nodes
        self.base, self.sock_dir = base, sock_dir
        self.sockets = {sock_dir / f"{m.name}.sock": (None if m.console else m.name)
                        for m in lab.machines}
        self._holders: dict[str, str] = {}          # machine (or "") -> hpn- machine name
        self._procs: list[subprocess.Popen] = []
        self._leaders: dict[str, int] = {}

    def _holder(self, key: str, argv: list[str]) -> None:
        name = machines.helper_name()
        self._holders[key] = name
        self._procs.append(subprocess.Popen(
            ["sudo", "systemd-nspawn", "-q", "--console=pipe", "--register=yes", "-M", name,
             "--private-network", "--read-only", f"--bind={self.sock_dir}:{_GRADE_IN}",
             "-D", str(self.base), *argv],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def _await_leaders(self) -> None:
        deadline = time.monotonic() + _LEADER_WAIT
        for key, name in self._holders.items():
            while (pid := _leader(name)) is None:
                if time.monotonic() > deadline:
                    msg = "стенд не поднялся: сетевые пространства машин не появились"
                    raise RuntimeError(msg)
                time.sleep(_POLL)
            self._leaders[key] = pid

    def _wire(self) -> None:
        binds = [f"--bind=/proc/{self._leaders[m.name]}/ns/net:/run/netns/{m.name}"
                 for m in self.lab.machines]
        res = subprocess.run(
            ["sudo", "systemd-nspawn", "-q", "--console=pipe", "--register=no",
             "-M", machines.helper_name(), "--read-only",
             "--capability=CAP_NET_ADMIN,CAP_SYS_ADMIN",
             f"--network-namespace-path=/proc/{self._leaders['']}/ns/net", *binds,
             "-D", str(self.base), "sh", "-c", wire_script(self.lab)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            msg = f"не удалось соединить машины стенда: {res.stderr.strip() or res.stdout.strip()}"
            raise RuntimeError(msg)

    def netns(self, machine: str) -> str:
        """Return the nspawn option that puts a machine into its (wired) network namespace."""
        return f"--network-namespace-path=/proc/{self._leaders[machine]}/ns/net"

    def start(self, port: int) -> None:
        """Write the machines' files, raise the holders, wire the network, boot the nodes."""
        hosts = {"/etc/hosts": hosts_text(self.lab)} if self.hosts else {}
        _write_files(self.console, hosts, root_owned=False)
        unit = f"/etc/systemd/system/{PORT_UNIT}"
        for runner in self.nodes.values():
            _write_files(runner, {**hosts, unit: port_unit(port)}, root_owned=True)
            res = runner.run(["sh", "-c", ("mkdir -p /etc/systemd/system/multi-user.target.wants && "
                              f"ln -sf {unit} /etc/systemd/system/multi-user.target.wants/{PORT_UNIT}")])
            if res.exit_code != 0:
                msg = f"не удалось подготовить машину стенда: {res.stderr.strip()}"
                raise RuntimeError(msg)
        self.sock_dir.mkdir(parents=True, exist_ok=True)
        for m in self.lab.machines:
            self._holder(m.name, [_SOCKET_ACTIVATE, "-l", f"127.0.0.1:{port}", _PROXYD,
                                  f"{_GRADE_IN}/{m.name}.sock"])
        self._holder("", ["sleep", "infinity"])
        self._await_leaders()
        self._wire()
        for name, runner in self.nodes.items():
            machine = machines.machine_name()
            runner.boot(machine, [self.netns(name), f"--hostname={name}",
                                  *nspawn_emulation_args(rootfs=runner.rootfs)])
            runner.live_machine = machine

    def console_args(self) -> list[str]:
        """Return the console's nspawn options: its network namespace and hostname."""
        return [self.netns(self.lab.console.name), f"--hostname={self.lab.console.name}"]

    def stop(self) -> None:
        """Power the nodes off and remove the holders (bridges and links go with them). Idempotent."""
        for runner in self.nodes.values():
            with contextlib.suppress(Exception):
                runner.poweroff()
            runner.live_machine = None
        for name in self._holders.values():
            subprocess.run(["sudo", "machinectl", "terminate", name], check=False, capture_output=True)
        for proc in self._procs:
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
        self._holders, self._procs, self._leaders = {}, [], {}
