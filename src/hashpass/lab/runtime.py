"""
A lab's live network: netns holders, the wiring, the nodes' boots (spec 2026-11-02 §6).

Nothing touches the host's network: every machine gets a network namespace held by a tiny
`hpn-` machine (`systemd-nspawn --private-network --read-only` on the base) which is also that
machine's grade relay -- `systemd-socket-activate -l 127.0.0.1:<port>` + `systemd-socket-proxyd`
to a host unix socket, so the console's hooks reach `127.0.0.1:$HP_PORT` as in a plain task.
One more holder is the switch: its netns gets a bridge per network and the veth pairs
(wire.py). Nodes then boot into their ready namespaces; the console joins its own.

The way out (§6а) is one more helper, on the host's network: slirp4netns from the base enters the
switch's netns, makes `tap0` there and carries its traffic through ordinary host sockets -- no
root route, NAT rule or bridge on the host (rootless podman does the same).
"""
from __future__ import annotations

import base64
import contextlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from hashpass import machines
from hashpass.emulation import nspawn_emulation_args
from hashpass.lab.config import LAB_MARK, PORT_UNIT, hosts_text, port_unit, resolv_text
from hashpass.lab.model import UPLINK_CIDR
from hashpass.lab.observe import (
    CONTROL_SOCK,
    Control,
    ControlServer,
    ViewForward,
    parse_net_dev,
    status_doc,
    write_status,
)
from hashpass.lab.wire import wire_script

if TYPE_CHECKING:
    from hashpass.lab.model import Lab
    from hashpass.runner.nspawn import NspawnRunner

_GRADE_IN = "/run/hp-grade"          # where a holder sees the host's socket directory
_SOCKET_ACTIVATE = "/usr/bin/systemd-socket-activate"
_PROXYD = "/usr/lib/systemd/systemd-socket-proxyd"
_SLIRP = "/usr/bin/slirp4netns"
_LEADER_WAIT = 20.0                  # seconds for a holder to come up
_POLL = 0.1
_STOP_TRIES = 6                      # x _STOP_WAIT: a slow holder gets 30 s to register and go
_STOP_WAIT = 5.0
_OBSERVE_IN = "/run/hp-lab"          # the observer's view of the feed + control (spec 2026-11-05)
_FEED_EVERY = 1.0                    # seconds between status.json updates


def _machine_states(names: list[str]) -> dict[str, str]:
    """Return machined name -> its State (running, degraded, opening…) for the ones registered."""
    if not names:
        return {}
    out = subprocess.run(["machinectl", "show", "-p", "Name", "-p", "State", *names],
                         capture_output=True, text=True, check=False).stdout
    states: dict[str, str] = {}
    for block in out.split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if fields.get("Name"):
            states[fields["Name"]] = fields.get("State", "")
    return states


def _state_word(state: str | None) -> str:
    if not state:
        return "stopped"
    return "running" if state in {"running", "degraded"} else "starting"


def grade_dir() -> Path:
    """
    Return a fresh directory for a lab's grade sockets, on a short path.

    AF_UNIX paths stop at 107 bytes; under a long HASHPASS_HOME the run dir would not fit.
    """
    return Path(tempfile.mkdtemp(prefix="hp-grade-"))


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
        """
        Bind the lab config to its prepared runners; `sock_dir` will hold the grade sockets.

        The way out needs a gateway somewhere and a base with slirp4netns + nft (runtime >= 50):
        a lab pinned to an older base runs as before, without the internet.
        """
        if lab.internet and not (lab.gateways() and all(
                (base / tool).is_file() for tool in (_SLIRP.lstrip("/"), "usr/sbin/nft"))):
            lab = replace(lab, internet=False)
        self.lab, self.hosts, self.console, self.nodes = lab, hosts, console, nodes
        self.base, self.sock_dir = base, sock_dir
        self.sockets = {sock_dir / f"{m.name}.sock": (None if m.console else m.name)
                        for m in lab.machines}
        self._holders: dict[str, str] = {}          # machine (or "") -> hpn- machine name
        self._procs: list[subprocess.Popen] = []
        self._leaders: dict[str, int] = {}
        # the observer (spec 2026-11-05): feed + control in observe_dir, views on host loopback
        self.observe_dir = sock_dir / "observe"
        self.control: Control | None = None
        self._control_server: ControlServer | None = None
        self.views: dict[str, ViewForward] = {}
        self._proc_fds: dict[str, int] = {}          # machine -> /proc/<holder> dir fd (no PID reuse)
        self._feed_stop = threading.Event()
        self._feed: threading.Thread | None = None

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

    def _uplink(self) -> None:
        """Start slirp4netns into the switch's netns (wire.py waits for its tap0)."""
        name = machines.helper_name()
        self._holders["<uplink>"] = name
        self._procs.append(subprocess.Popen(
            ["sudo", "systemd-nspawn", "-q", "--console=pipe", "--register=yes", "-M", name,
             "--read-only", "--capability=CAP_NET_ADMIN,CAP_SYS_ADMIN", "--bind=/dev/net/tun",
             f"--bind-ro=/proc/{self._leaders['']}/ns/net:/run/netns/switch",
             "-D", str(self.base), _SLIRP, "--configure", "--mtu=65520", "--disable-host-loopback",
             f"--cidr={UPLINK_CIDR}", "--netns-type=path", "/run/netns/switch", "tap0"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def _switch_sh(self, script: str, *, machines_too: bool) -> subprocess.CompletedProcess:
        """Run an sh script in the switch's netns with CAP_NET_ADMIN (machines' netns at /run/netns)."""
        binds = ([f"--bind=/proc/{self._leaders[m.name]}/ns/net:/run/netns/{m.name}"
                  for m in self.lab.machines] if machines_too else [])
        return subprocess.run(
            ["sudo", "systemd-nspawn", "-q", "--console=pipe", "--register=no",
             "-M", machines.helper_name(), "--read-only",
             "--capability=CAP_NET_ADMIN,CAP_SYS_ADMIN",
             f"--network-namespace-path=/proc/{self._leaders['']}/ns/net", "--private-network",
             *binds,
             "-D", str(self.base), "sh", "-c", script],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)

    def _wire(self) -> None:
        res = self._switch_sh(wire_script(self.lab), machines_too=True)
        if res.returncode != 0:
            msg = f"не удалось соединить машины стенда: {res.stderr.strip() or res.stdout.strip()}"
            raise RuntimeError(msg)

    def _control_exec(self, script: str) -> None:
        """Run one control request: one helper per request, in the switch (spec 2026-11-05 §5)."""
        res = self._switch_sh(f"set -e\n{script}\n", machines_too=False)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or res.stdout.strip() or f"код {res.returncode}")

    def _counters(self) -> dict[str, dict[str, dict[str, int]]]:
        out = {}
        for name, fd in self._proc_fds.items():
            try:
                fd2 = os.open("net/dev", os.O_RDONLY, dir_fd=fd)
                with os.fdopen(fd2, encoding="utf-8") as f:
                    out[name] = parse_net_dev(f.read())
            except OSError:
                continue                   # the holder is gone: no counters, not zeros
        return out

    def status(self) -> dict:
        """Return the status feed's current document (spec 2026-11-05 §4)."""
        live = {name: r.live_machine for name, r in self.nodes.items() if r.live_machine}
        found = _machine_states(list(live.values()))
        states = {name: _state_word(found.get(machine)) for name, machine in live.items()}
        states[self.lab.console.name] = "running"
        ctl = self.control
        return status_doc(self.lab, states=states, counters=self._counters(),
                          links=dict(ctl.links) if ctl else {}, netem=dict(ctl.netem) if ctl else {},
                          views={name: v.port for name, v in self.views.items()}, ts=time.time())

    def _feed_loop(self) -> None:
        while not self._feed_stop.wait(_FEED_EVERY):
            with contextlib.suppress(Exception):
                write_status(self.observe_dir, self.status())

    def _start_observer(self) -> None:
        """Make /run/hp-lab for the observer: the first status.json and the control socket."""
        self.observe_dir.mkdir(mode=0o755, exist_ok=True)
        self.observe_dir.chmod(0o755)
        for name, pid in self._leaders.items():
            if name and name in {m.name for m in self.lab.machines}:
                with contextlib.suppress(OSError):
                    self._proc_fds[name] = os.open(f"/proc/{pid}", os.O_RDONLY | os.O_DIRECTORY)
        self.control = Control(self.lab, execute=self._control_exec, status=self.status)
        self._control_server = ControlServer(self.observe_dir / CONTROL_SOCK, self.control)
        self._control_server.start()
        write_status(self.observe_dir, self.status())

    def _observer_args(self, machine: str) -> list[str]:
        obs = self.lab.observer
        if obs is None or obs.name != machine:
            return []
        return [f"--bind-ro={self.observe_dir}:{_OBSERVE_IN}"]

    def view_urls(self) -> dict[str, str]:
        """Return machine -> the address its `view` port has on the student's computer."""
        return {name: f"http://127.0.0.1:{v.port}/" for name, v in self.views.items()}

    def netns(self, machine: str) -> list[str]:
        """
        Return the nspawn options that put a machine into its (wired) network namespace.

        A joined namespace alone gives no CAP_NET_ADMIN and a read-only /proc/sys/net: a router
        lab could neither `ip route` nor `sysctl net.ipv4.ip_forward=1`. With `--private-network`
        too, nspawn keeps the joined namespace (probed 2026-11-02) and grants both, scoped to it.
        """
        return [f"--network-namespace-path=/proc/{self._leaders[machine]}/ns/net",
                "--private-network"]

    def start(self, port: int) -> None:  # noqa: C901
        """Write the machines' files, raise the holders, wire the network, boot the nodes."""
        hosts = {"/etc/hosts": hosts_text(self.lab)} if self.hosts else {}
        # the prompt names the machine in a lab (hp-bashrc reads the mark)
        hosts[LAB_MARK] = f"{self.lab.name}\n"
        if self.lab.internet:
            hosts["/etc/resolv.conf"] = resolv_text()
        # the base names every machine «hashpass» in /etc/hostname, and systemd prefers it to
        # nspawn's --hostname: each lab machine is called by its own name
        _write_files(self.console, {**hosts, "/etc/hostname": f"{self.lab.console.name}\n"},
                     root_owned=False)
        unit = f"/etc/systemd/system/{PORT_UNIT}"
        for name, runner in self.nodes.items():
            _write_files(runner, {**hosts, "/etc/hostname": f"{name}\n", unit: port_unit(port)},
                         root_owned=True)
            # a node has no terminal: the base's console autologin (hp-console powers the machine
            # off when its shell ends) must not run there -- the student comes in over ssh
            res = runner.run(["sh", "-c", ("mkdir -p /etc/systemd/system/multi-user.target.wants && "
                              f"ln -sf {unit} /etc/systemd/system/multi-user.target.wants/{PORT_UNIT} && "
                              "ln -sf /dev/null /etc/systemd/system/console-getty.service")])
            if res.exit_code != 0:
                msg = f"не удалось подготовить машину стенда: {res.stderr.strip()}"
                raise RuntimeError(msg)
        self.sock_dir.mkdir(parents=True, exist_ok=True)
        for m in self.lab.machines:
            grade = [_SOCKET_ACTIVATE, "-l", f"127.0.0.1:{port}", _PROXYD, f"{_GRADE_IN}/{m.name}.sock"]
            if m.view is None:
                self._holder(m.name, grade)
            else:
                # the holder sits in the machine's netns: a second relay, the other way round --
                # a unix socket the host connects to -> the machine's own 127.0.0.1:<view>.
                # the socket is root's 0644 (socket-activate ignores umask): the student's
                # hashpass must connect to it, so it is opened up once it exists
                sock = f"{_GRADE_IN}/view-{m.name}.sock"
                view = (f"{_SOCKET_ACTIVATE} -l {sock} {_PROXYD} 127.0.0.1:{int(m.view)} & "
                        f"i=0; while [ ! -S {sock} ] && [ $i -lt 100 ]; do i=$((i+1)); sleep 0.05; done; "
                        f"chmod 666 {sock}; exec {' '.join(grade)}")
                self._holder(m.name, ["/bin/sh", "-c", view])
        self._holder("", ["sleep", "infinity"])
        self._await_leaders()
        if self.lab.internet:
            self._uplink()
        self._wire()
        if self.lab.observer is not None:
            self._start_observer()
        for name, runner in self.nodes.items():
            machine = machines.machine_name()
            runner.boot(machine, [*self.netns(name), f"--hostname={name}", *self._observer_args(name),
                                  *nspawn_emulation_args(rootfs=runner.rootfs)])
            runner.live_machine = machine
        for m in self.lab.machines:
            if m.view is not None:
                fwd = ViewForward(self.sock_dir / f"view-{m.name}.sock", preferred=m.view)
                fwd.start()
                self.views[m.name] = fwd
        if self.lab.observer is not None:
            self._feed = threading.Thread(target=self._feed_loop, daemon=True)
            self._feed.start()

    def console_args(self) -> list[str]:
        """Return the console's nspawn options: its network namespace and hostname."""
        return [*self.netns(self.lab.console.name), f"--hostname={self.lab.console.name}",
                *self._observer_args(self.lab.console.name)]

    def stop(self) -> None:
        """Power the nodes off and remove the holders (bridges and links go with them). Idempotent."""
        # the observer's services first: nothing may touch the switch or the sockets after this
        self._feed_stop.set()
        if self._feed is not None:
            self._feed.join(timeout=_STOP_WAIT)
            self._feed = None
        for fwd in self.views.values():
            fwd.stop()
        self.views = {}
        if self._control_server is not None:
            self._control_server.stop()
            self._control_server = None
        for fd in self._proc_fds.values():
            with contextlib.suppress(OSError):
                os.close(fd)
        self._proc_fds = {}
        for runner in self.nodes.values():
            with contextlib.suppress(Exception):
                runner.poweroff()
            runner.live_machine = None
        # A holder still registering when we gave up is not in machined yet: its `sudo` process is
        # root's, so we cannot kill it -- terminate by name again until it is gone.
        for name, proc in zip(self._holders.values(), self._procs, strict=True):
            for _ in range(_STOP_TRIES):
                subprocess.run(["sudo", "machinectl", "terminate", name], check=False, capture_output=True)
                try:
                    proc.wait(timeout=_STOP_WAIT)
                    break
                except subprocess.TimeoutExpired:
                    continue
        self._holders, self._procs, self._leaders = {}, [], {}
        shutil.rmtree(self.sock_dir, ignore_errors=True)
