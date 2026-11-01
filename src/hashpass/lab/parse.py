"""
Labfile parser: `lab <name>:<ver>`, `machine` blocks, and the task itself (spec 2026-11-02 §1а).

Like docker-compose for Taskfiles: each machine is built from its own Taskfile (`build <dir>`) or
taken as an image (`image <ref>`); the Labfile ties them with networks and holds the task (say,
read, stage… exactly as in a Taskfile; `check live on <machine>` checks inside a machine).
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from hashpass.lab.model import MAX_IFACES, MAX_MACHINES, MAX_NETS, Lab, Machine, NetAddr
from hashpass.recipe.parse import _kw_value, _significant, parse_recipe

if TYPE_CHECKING:
    from hashpass.recipe.model import Recipe

LABFILE = "Labfile"
_MACHINE_NAME = re.compile(r"[a-z][a-z0-9-]{0,14}")
_NET_NAME = re.compile(r"[a-z][a-z0-9-]{0,11}")
_BUILD_STEPS = ("from", "run", "copy", "user", "image")


def _fail(msg: str) -> NoReturn:
    raise ValueError(msg)


def _parse_machine(name: str, body: list[str]) -> Machine:
    if not _MACHINE_NAME.fullmatch(name):
        _fail(f"имя машины {name!r}: строчные латинские буквы, цифры и «-», до 15 знаков, с буквы")
    build = image = gw = None
    console = False
    nets: list[NetAddr] = []
    for line in body:
        kw, value = _kw_value(line)
        value = value.strip()
        if kw == "console" and not value:
            console = True
        elif kw == "build" and value:
            build = value
        elif kw == "image" and value:
            image = value
        elif kw == "gw" and value:
            gw = value
        elif kw == "net":
            net, _, addr = value.partition(" ")
            nets.append(NetAddr(net, addr.strip()))
        else:
            _fail(f"машина {name}: непонятная строка {line!r} (console, build, image, net, gw)")
    if (build is None) == (image is None):
        _fail(f"машина {name}: нужен ровно один из build или image")
    return Machine(name, build=build, image=image, nets=tuple(nets), gw=gw, console=console)


def _iface(m: Machine, n: NetAddr) -> ipaddress.IPv4Interface | ipaddress.IPv6Interface:
    if not _NET_NAME.fullmatch(n.net):
        _fail(f"машина {m.name}: имя сети {n.net!r} — строчные латинские буквы, цифры и «-», до 12 знаков")
    try:
        if "/" not in n.addr:
            raise ValueError(n.addr)  # noqa: TRY301
        return ipaddress.ip_interface(n.addr)
    except ValueError:
        _fail(f"машина {m.name}: адрес {n.addr!r} — нужен вид 10.0.0.10/24")


def _check_gw(m: Machine, mine: list[ipaddress.IPv4Interface | ipaddress.IPv6Interface]) -> None:
    try:
        gw = ipaddress.ip_address(m.gw or "")
    except ValueError:
        _fail(f"машина {m.name}: gw {m.gw!r} — не IP-адрес")
    if not any(gw in i.network and gw != i.ip for i in mine):
        _fail(f"машина {m.name}: gw {m.gw} не лежит ни в одной из её сетей")


def _check_nets(lab: Lab) -> None:
    subnets: dict[str, object] = {}
    used: dict[str, str] = {}
    for m in lab.machines:
        if len(m.nets) > MAX_IFACES:
            _fail(f"машина {m.name}: больше {MAX_IFACES} интерфейсов")
        mine = []
        for n in m.nets:
            iface = _iface(m, n)
            if subnets.setdefault(n.net, iface.network) != iface.network:
                _fail(f"машина {m.name}: {n.addr} не в подсети сети {n.net} ({subnets[n.net]})")
            if (prev := used.get(n.ip)) is not None:
                _fail(f"машина {m.name}: адрес {n.ip} уже занят машиной {prev}")
            used[n.ip] = m.name
            mine.append(iface)
        if m.gw is not None:
            _check_gw(m, mine)
    if len(lab.networks) > MAX_NETS:
        _fail(f"в стенде больше {MAX_NETS} сетей")


def validate(lab: Lab) -> None:
    """Check a lab's machines and network; raise ValueError with a plain Russian message."""
    names = [m.name for m in lab.machines]
    for name in names:
        if names.count(name) > 1:
            _fail(f"машина {name}: повтор имени")
    if len(lab.machines) > MAX_MACHINES:
        _fail(f"в стенде больше {MAX_MACHINES} машин")
    consoles = [m.name for m in lab.machines if m.console]
    if len(consoles) != 1:
        _fail("в стенде должна быть ровно одна консоль (строка console в блоке machine), "
              f"а их {len(consoles)}")
    if not lab.console.nets:
        _fail(f"консоль {lab.console.name} не подключена ни к одной сети (строка net)")
    _check_nets(lab)


def parse_labfile(text: str) -> tuple[Lab, Recipe]:
    """Parse a Labfile into the lab (machines, network) and the task Recipe (no build steps)."""
    lines = _significant(text)
    name: str | None = None
    version = "1"
    machines: list[Machine] = []
    rest: list[str] = []
    i = 0
    while i < len(lines):
        indent, content = lines[i]
        kw, value = _kw_value(content)
        if indent == 0 and kw == "lab":
            if name is not None:
                _fail("строка lab — только одна")
            name, _, ver = value.strip().partition(":")
            version = ver or "1"
            i += 1
        elif indent == 0 and kw == "machine":
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i][0] > 0:
                body.append(lines[i][1])
                i += 1
            machines.append(_parse_machine(value.strip(), body))
        else:
            if indent == 0 and kw in _BUILD_STEPS:
                _fail(f"{kw} в Labfile не бывает: шаги сборки — в Taskfile машины (build <каталог>)")
            rest.append(" " * indent + content)
            i += 1
    if not name:
        _fail("в Labfile нет строки lab <имя>:<версия>")
    lab = Lab(name, version, tuple(machines))
    validate(lab)
    recipe = parse_recipe("\n".join([f"image {name}:{version}", *rest]) + "\n")
    known = {m.name for m in lab.machines}
    for stage in recipe.stages:
        if stage.check_node is not None and stage.check_node not in known:
            _fail(f"check live on {stage.check_node}: в стенде нет машины {stage.check_node}")
    return lab, replace(recipe, parents=(), steps=())


def load_labfile(path: Path) -> tuple[Lab, Recipe]:
    """Read and parse a Labfile from disk."""
    return parse_labfile(Path(path).read_text(encoding="utf-8"))


def labfile_of(path: Path) -> Path | None:
    """Return the Labfile `path` names: the file itself, or a folder's Labfile (no Taskfile there)."""
    path = Path(path)
    if path.is_dir():
        if (path / LABFILE).is_file() and not (path / "Taskfile").is_file():
            return path / LABFILE
        return None
    return path if path.name == LABFILE else None
