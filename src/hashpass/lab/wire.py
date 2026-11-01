"""
The lab's wiring script: run once, inside the switch's network namespace (spec 2026-11-02 §6).

Every machine's netns is bound at /run/netns/<name>. A bridge per network lives in the switch;
each interface is a veth pair, the switch end on the bridge, the machine end `eth<k>` with its
address. Nothing is created in the host's netns -- Docker's FORWARD DROP never sees these frames.
"""
from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hashpass.lab.model import Lab


def wire_script(lab: Lab) -> str:
    """Return the sh script that builds the lab's bridges, links, addresses and routes."""
    q = shlex.quote
    out = ["set -e", "ip link set lo up"]
    for net in lab.networks:
        out += [f"ip link add br-{net} type bridge", f"ip link set br-{net} up"]
    for i, m in enumerate(lab.machines):
        ns = q(m.name)
        out.append(f"ip -n {ns} link set lo up")
        # systemd-sysctl does not run in a container (read-only /proc/sys), so a fresh netns keeps
        # ping_group_range «1 0» and a plain user's ping fails «missing cap_net_raw»
        out.append(f"ip netns exec {ns} sysctl -qw net.ipv4.ping_group_range='0 2147483647'")
        for k, n in enumerate(m.nets):
            veth = f"v{i}e{k}"
            out += [f"ip link add {veth} type veth peer name eth{k} netns {ns}",
                    f"ip link set {veth} master br-{n.net} up",
                    f"ip -n {ns} addr add {q(n.addr)} dev eth{k}",
                    f"ip -n {ns} link set eth{k} up"]
        if m.gw:
            out.append(f"ip -n {ns} route add default via {q(m.gw)}")
    return "\n".join(out) + "\n"
