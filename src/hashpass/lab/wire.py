"""
The lab's wiring script: run once, inside the switch's network namespace (spec 2026-11-02 §6).

Every machine's netns is bound at /run/netns/<name>. A bridge per network lives in the switch;
each interface is a veth pair, the switch end on the bridge, the machine end `eth<k>` with its
address. Nothing is created in the host's netns -- Docker's FORWARD DROP never sees these frames.

Internet (§6а): the switch is also the lab's router out. slirp4netns (runtime.py) gives it `tap0`
with a default route through the host's own sockets; each network's gateway address sits on its
bridge, and the switch masquerades whatever leaves by tap0. The host's firewall is never touched.
"""
from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hashpass.lab.model import Lab


_UPLINK_WAIT = 15     # seconds for slirp4netns to bring tap0 up


def wire_script(lab: Lab) -> str:
    """Return the sh script that builds the lab's bridges, links, addresses and routes."""
    q = shlex.quote
    out = ["set -e", "ip link set lo up",
           # br_netfilter (Docker loads it on the host) would show the switch's conntrack every
           # bridged frame: pc -> lab router on lan registers a flow un-NATed, and the same packet
           # routed back in from wan then skips masquerade (probed 2026-11-02). Per netns, the
           # host keeps its own value.
           ("for f in iptables ip6tables arptables; do p=/proc/sys/net/bridge/bridge-nf-call-$f; "
            "[ -e $p ] && echo 0 > $p; done; true")]
    gws = lab.gateways()
    prefix = {n.net: n.addr.split("/", 1)[1] for m in lab.machines for n in m.nets}
    for net in lab.networks:
        out += [f"ip link add br-{net} type bridge", f"ip link set br-{net} up"]
        if net in gws:
            out.append(f"ip addr add {gws[net]}/{prefix[net]} dev br-{net}")
    if lab.internet:
        out += ["sysctl -qw net.ipv4.ip_forward=1",
                "nft add table ip hp",
                "nft add chain ip hp post '{ type nat hook postrouting priority 100; }'",
                "nft add rule ip hp post oifname tap0 masquerade",
                # slirp4netns comes up beside us: the first command must already find the way out
                (f"i=0; while ! ip route show default | grep -q tap0; do i=$((i+1)); "
                 f"[ $i -gt {_UPLINK_WAIT * 10} ] && exit 3; sleep 0.1; done")]
    tail = [f"ip route add {net} via {via}" for net, via in lab.return_routes().items()]
    for i, m in enumerate(lab.machines):
        ns = q(m.name)
        out.append(f"ip -n {ns} link set lo up")
        # systemd-sysctl does not run in a container (read-only /proc/sys), so a fresh netns keeps
        # ping_group_range «1 0» and a plain user's ping fails «missing cap_net_raw»
        out.append(f"ip netns exec {ns} sysctl -qw net.ipv4.ping_group_range='0 2147483647'")
        # a new netns copies IPv4 settings from the host's (forwarding is on wherever Docker runs):
        # every machine starts as a plain host, a lab router is switched on by the student
        out.append(f"ip netns exec {ns} sysctl -qw net.ipv4.ip_forward=0")
        for k, n in enumerate(m.nets):
            veth = f"v{i}e{k}"
            out += [f"ip link add {veth} type veth peer name eth{k} netns {ns}",
                    f"ip link set {veth} master br-{n.net} up",
                    f"ip -n {ns} addr add {q(n.addr)} dev eth{k}",
                    f"ip -n {ns} link set eth{k} up"]
        if (gw := lab.default_route(m)) is not None:
            out.append(f"ip -n {ns} route add default via {q(gw)}")
    if lab.internet:
        out += tail            # after the veths: the router's address must be reachable first
    return "\n".join(out) + "\n"
