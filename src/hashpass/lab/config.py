"""
A lab's layer: `/.hp-nodes/<machine>/` (each node's rootfs delta) + `/.hp-nodes/lab.json`.

The lab ref is an ordinary image whose parent is the console's image (spec 2026-11-02 §1а), so the
pool stores and serves it unchanged. The console never sees `/.hp-nodes`: a mask layer goes on top.
"""
from __future__ import annotations

import json
from pathlib import Path

from hashpass.lab.model import UPLINK_DNS, Lab, Machine, NetAddr

NODES_DIR = ".hp-nodes"
LAB_JSON = "lab.json"
PORT_UNIT = "hp-port.service"
LAB_MARK = "/etc/hp-lab"        # in every lab machine: the prompt shows the machine's name


def lab_to_dict(lab: Lab, *, hosts: bool) -> dict:
    """Serialize a lab (+ whether /etc/hosts is written) for lab.json."""
    return {"name": lab.name, "version": lab.version, "hosts": hosts, "internet": lab.internet,
            "machines": [
        {"name": m.name, "console": m.console, "gw": m.gw,
         "nets": [{"net": n.net, "addr": n.addr} for n in m.nets]} for m in lab.machines]}


def lab_from_dict(data: dict) -> tuple[Lab, bool]:
    """Rebuild a lab (machines without their build source) and its hosts flag from lab.json."""
    machines = tuple(Machine(name=m["name"], console=bool(m.get("console")), gw=m.get("gw"),
                             nets=tuple(NetAddr(n["net"], n["addr"]) for n in m.get("nets", [])))
                     for m in data["machines"])
    lab = Lab(data["name"], data["version"], machines, internet=bool(data.get("internet", True)))
    return lab, bool(data.get("hosts", True))


def find_lab(lowers: list[Path]) -> tuple[Lab, bool, Path] | None:
    """Return (lab, hosts, its layer) from the topmost layer holding `.hp-nodes/lab.json`, else None."""
    for layer in lowers:
        path = Path(layer) / NODES_DIR / LAB_JSON
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lab, hosts = lab_from_dict(data)
        return lab, hosts, Path(layer)
    return None


def has_nodes(lowers: list[Path]) -> bool:
    """Whether any layer of a chain carries lab machines."""
    return any((Path(layer) / NODES_DIR).is_dir() for layer in lowers)


def console_lowers(lowers: list[Path], mask: Path | None) -> list[Path]:
    """Put the mask on top of a chain that carries lab machines; any other chain is left as is."""
    if mask is None or not has_nodes(lowers):
        return list(lowers)
    return [Path(mask), *lowers]


def hosts_text(lab: Lab) -> str:
    """/etc/hosts for every machine of the lab: localhost + `<ip> <name>` for each address."""
    lines = ["127.0.0.1\tlocalhost", "::1\tlocalhost ip6-localhost ip6-loopback"]
    lines += [f"{n.ip}\t{m.name}" for m in lab.machines for n in m.nets]
    return "\n".join(lines) + "\n"


def resolv_text() -> str:
    """/etc/resolv.conf for every machine: the uplink's DNS (reached through the gateways)."""
    return f"nameserver {UPLINK_DNS}\n"


def port_unit(port: int) -> str:
    """Return a node's oneshot unit putting the grade port in /run/hp/port for the hooks (hp-bashrc)."""
    return ("[Unit]\nDescription=hashpass lab grade port\nDefaultDependencies=no\n"
            "After=local-fs.target\n\n[Service]\nType=oneshot\n"
            "ExecStart=/bin/sh -c 'mkdir -p /run/hp && chmod 755 /run/hp && "
            f"echo {int(port)} > /run/hp/port && chmod 644 /run/hp/port'\n\n"
            "[Install]\nWantedBy=multi-user.target\n")
