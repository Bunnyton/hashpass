"""Lab layer config, /etc/hosts, the mask placement, the wiring script (spec 2026-11-02)."""
import json

import pytest

from hashpass.lab.config import (
    LAB_JSON,
    NODES_DIR,
    console_lowers,
    find_lab,
    hosts_text,
    lab_from_dict,
    lab_to_dict,
    port_unit,
)
from hashpass.lab.parse import parse_labfile
from hashpass.lab.wire import wire_script

_ROUTED = """\
lab r:1
machine pc
  console
  build pc
  net lan 10.0.0.10/24
  gw 10.0.0.1
machine web
  build web
  net lan 10.0.0.20/24
machine router
  build router
  net lan 10.0.0.1/24
  net wan 192.168.50.1/24
machine db
  build db
  net wan 192.168.50.30/24
  gw 192.168.50.1
say "x"
stage
  solve true
"""


@pytest.fixture
def lab():
    return parse_labfile(_ROUTED)[0]


@pytest.mark.tier1
def test_lab_json_round_trip(lab) -> None:
    back, hosts = lab_from_dict(json.loads(json.dumps(lab_to_dict(lab, hosts=False))))
    assert hosts is False
    assert [m.name for m in back.machines] == ["pc", "web", "router", "db"]
    assert back.console.name == "pc"
    assert back.machines[2].nets == lab.machines[2].nets
    assert back.machines[3].gw == "192.168.50.1"


@pytest.mark.tier1
def test_find_lab_takes_the_topmost_layer(tmp_path, lab) -> None:
    top, low, plain = tmp_path / "top", tmp_path / "low", tmp_path / "plain"
    for d in (top, low):
        (d / NODES_DIR).mkdir(parents=True)
    plain.mkdir()
    (low / NODES_DIR / LAB_JSON).write_text(json.dumps(lab_to_dict(lab, hosts=True)))
    found = find_lab([plain, top, low])
    assert found is not None and found[2] == low and found[1] is True
    assert find_lab([plain]) is None


@pytest.mark.tier1
def test_the_mask_goes_only_on_a_chain_with_machines(tmp_path) -> None:
    a, b, mask = tmp_path / "a", tmp_path / "b", tmp_path / "mask"
    a.mkdir()
    b.mkdir()
    assert console_lowers([a, b], mask) == [a, b]
    (b / NODES_DIR).mkdir()
    assert console_lowers([a, b], mask) == [mask, a, b]


@pytest.mark.tier1
def test_hosts_name_every_address(lab) -> None:
    text = hosts_text(lab)
    assert "10.0.0.20\tweb\n" in text
    assert "10.0.0.10\tpc\n" in text
    assert "10.0.0.1\trouter\n" in text and "192.168.50.1\trouter\n" in text
    assert text.startswith("127.0.0.1\tlocalhost\n")


@pytest.mark.tier1
def test_port_unit_writes_the_port() -> None:
    unit = port_unit(41234)
    assert "echo 41234 > /run/hp/port" in unit
    assert "WantedBy=multi-user.target" in unit


@pytest.mark.tier1
def test_wire_script_builds_two_subnets_and_routes(lab) -> None:
    script = wire_script(lab).splitlines()
    assert script[0] == "set -e"
    assert "ip link add br-lan type bridge" in script
    assert "ip link add br-wan type bridge" in script
    assert "ip link add v2e1 type veth peer name eth1 netns router" in script
    assert "ip link set v2e1 master br-wan up" in script
    assert "ip -n router addr add 192.168.50.1/24 dev eth1" in script
    assert "ip -n db route add default via 192.168.50.1" in script
    assert "ip -n pc route add default via 10.0.0.1" in script
    assert not any("route" in line for line in script if line.startswith("ip -n web"))
    # a plain user's ping: ICMP sockets for every group, in each machine's own netns
    assert "ip netns exec web sysctl -qw net.ipv4.ping_group_range='0 2147483647'" in script
    # a fresh netns inherits the host's forwarding: every machine starts as a plain host
    assert "ip netns exec router sysctl -qw net.ipv4.ip_forward=0" in script
