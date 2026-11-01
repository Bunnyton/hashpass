"""Lab model: the machines of a Labfile and their network interfaces."""
from __future__ import annotations

from dataclasses import dataclass

MAX_MACHINES = 8
MAX_NETS = 4
MAX_IFACES = 4


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
