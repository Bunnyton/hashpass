"""Lab model: the machines of a Labfile and their network interfaces."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

MAX_MACHINES = 8
MAX_NETS = 4
MAX_IFACES = 4
# The uplink (slirp4netns in the switch's netns): its own range, out of the authors' way.
UPLINK_CIDR = "100.64.250.0/24"
UPLINK_DNS = "100.64.250.3"
_V4 = 4


@dataclass(frozen=True)
class NetAddr:
    """One interface: `net <net> <addr>` -- the network's name and the address with its prefix."""

    net: str
    addr: str          # "10.0.0.10/24"

    @property
    def ip(self) -> str:
        """The address without its prefix."""
        return self.addr.split("/", 1)[0]


@dataclass(frozen=True)
class Machine:
    """A `machine` block: built from a Taskfile (`build`) or taken as an image (`image`)."""

    name: str
    build: str | None = None
    image: str | None = None
    nets: tuple[NetAddr, ...] = ()
    gw: str | None = None
    console: bool = False


@dataclass(frozen=True)
class Lab:
    """A lab: its name/version and machines, exactly one of them the student's console."""

    name: str
    version: str
    machines: tuple[Machine, ...]
    internet: bool = True      # `settings internet off`: no gateway, no way out

    @property
    def console(self) -> Machine:
        """The machine the student sits at."""
        return next(m for m in self.machines if m.console)

    @property
    def nodes(self) -> tuple[Machine, ...]:
        """Every other machine (booted in the background)."""
        return tuple(m for m in self.machines if not m.console)

    @property
    def networks(self) -> tuple[str, ...]:
        """Network names in order of first use."""
        return tuple(dict.fromkeys(n.net for m in self.machines for n in m.nets))

    def gateways(self) -> dict[str, str]:
        """
        Return each network's internet gateway: its first address, as in docker-compose.

        A machine holding that address is the network's router instead (no gateway there);
        IPv6 networks and ones too small for a spare address get none.
        """
        if not self.internet:
            return {}
        taken = {n.ip for m in self.machines for n in m.nets}
        out: dict[str, str] = {}
        for m in self.machines:
            for n in m.nets:
                net = ipaddress.ip_interface(n.addr).network
                if n.net in out or net.version != _V4 or net.num_addresses < 4:  # noqa: PLR2004
                    continue
                first = str(net.network_address + 1)
                if first not in taken:
                    out[n.net] = first
        return out

    def default_route(self, machine: Machine) -> str | None:
        """Return a machine's default gateway: its own `gw`, else the gateway of its first network with one."""
        if machine.gw:
            return machine.gw
        gws = self.gateways()
        return next((gws[n.net] for n in machine.nets if n.net in gws), None)

    def return_routes(self) -> dict[str, str]:
        """
        Return the switch's routes back to networks behind a lab router: subnet -> router's address.

        A network whose .1 is a lab machine has no gateway; when that machine also sits on a network
        with one, replies from outside reach the switch addressed to the hidden subnet and go to it.
        """
        gws = self.gateways()
        out: dict[str, str] = {}
        for m in self.machines:
            uplinks = [n for n in m.nets if n.net in gws]
            if not uplinks:
                continue
            for n in m.nets:
                net = ipaddress.ip_interface(n.addr).network
                if n.net not in gws and net.version == _V4 and n.ip == str(net.network_address + 1):
                    out.setdefault(str(net), uplinks[0].ip)
        return out
