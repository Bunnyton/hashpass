"""Internet in a lab: like docker-compose, each network's .1 is a NAT gateway out (spec 2026-11-02 §6а)."""
import json

import pytest

from hashpass.lab.config import lab_from_dict, lab_to_dict, resolv_text
from hashpass.lab.model import UPLINK_DNS
from hashpass.lab.parse import parse_labfile
from hashpass.lab.runtime import LabRuntime
from hashpass.lab.wire import wire_script

_HELLO = """\
lab h:1
machine pc
  console
  build pc
  net lan 10.20.0.10/24
machine web
  build web
  net lan 10.20.0.20/24
say "x"
stage
  solve true
"""

_ROUTED = """\
lab r:1
machine pc
  console
  build pc
  net lan 10.0.0.10/24
  gw 10.0.0.1
machine router
  build router
  net lan 10.0.0.1/24
  net wan 192.168.50.2/24
say "x"
stage
  solve true
"""


@pytest.mark.tier1
def test_internet_is_on_by_default_with_the_gateway_on_dot_one() -> None:
    lab, _ = parse_labfile(_HELLO)
    assert lab.internet is True
    assert lab.gateways() == {"lan": "10.20.0.1"}
    assert lab.default_route(lab.machines[1]) == "10.20.0.1"


@pytest.mark.tier1
def test_a_machine_on_dot_one_is_that_networks_router() -> None:
    lab, _ = parse_labfile(_ROUTED)
    assert lab.gateways() == {"wan": "192.168.50.1"}
    pc, router = lab.machines
    assert lab.default_route(pc) == "10.0.0.1"           # its own gw wins
    assert lab.default_route(router) == "192.168.50.1"   # out through wan


@pytest.mark.tier1
def test_settings_internet_off() -> None:
    lab, _ = parse_labfile(_HELLO.replace('say "x"', 'settings\n  internet off\nsay "x"'))
    assert lab.internet is False
    assert lab.gateways() == {}
    assert lab.default_route(lab.machines[1]) is None
    script = wire_script(lab)
    assert "masquerade" not in script and "dev br-lan" not in script and "route add default" not in script


@pytest.mark.tier1
def test_wire_script_gives_the_gateway_and_nat() -> None:
    lab, _ = parse_labfile(_ROUTED)
    script = wire_script(lab).splitlines()
    assert "ip addr add 192.168.50.1/24 dev br-wan" in script
    assert not any("dev br-lan" in s and "addr add" in s for s in script)
    assert "ip -n router route add default via 192.168.50.1" in script
    assert "ip -n pc route add default via 10.0.0.1" in script
    assert "sysctl -qw net.ipv4.ip_forward=1" in script
    # bridged frames stay out of the switch's conntrack, or routed-back flows skip masquerade
    assert any("bridge-nf-call-$f" in s for s in script)
    assert any("masquerade" in s and "tap0" in s for s in script)
    # the switch waits for its uplink, so the first command already has the internet
    assert any("tap0" in s and "while" in s for s in script)


@pytest.mark.tier1
def test_the_uplink_range_is_not_a_lab_network() -> None:
    with pytest.raises(ValueError, match=r"100\.64\.250"):
        parse_labfile(_HELLO.replace("10.20.0.", "100.64.250."))


@pytest.mark.tier1
def test_lab_json_keeps_internet() -> None:
    lab, _ = parse_labfile(_HELLO.replace('say "x"', 'settings\n  internet off\nsay "x"'))
    back, _ = lab_from_dict(json.loads(json.dumps(lab_to_dict(lab, hosts=True))))
    assert back.internet is False
    old = lab_to_dict(lab, hosts=True)
    del old["internet"]
    assert lab_from_dict(old)[0].internet is True


@pytest.mark.tier1
def test_resolv_conf_points_at_the_uplink_dns() -> None:
    assert resolv_text() == f"nameserver {UPLINK_DNS}\n"


@pytest.mark.tier1
def test_the_switch_routes_back_to_networks_behind_a_lab_router() -> None:
    # pc sits behind router (lan .1); router reaches the gateway on wan. A reply coming in for
    # 10.0.0.10 must find its way back through router, as a provider routes a customer's subnet.
    lab, _ = parse_labfile(_ROUTED)
    assert lab.return_routes() == {"10.0.0.0/24": "192.168.50.2"}
    assert "ip route add 10.0.0.0/24 via 192.168.50.2" in wire_script(lab).splitlines()
    hello, _ = parse_labfile(_HELLO)
    assert hello.return_routes() == {}


@pytest.mark.tier1
def test_a_lab_on_an_older_base_runs_without_the_internet(tmp_path) -> None:
    lab, _ = parse_labfile(_HELLO)
    old = LabRuntime(lab, True, None,  # noqa: FBT003
                      {}, tmp_path, tmp_path / "s")   # no slirp4netns, no nft
    assert old.lab.internet is False
    for tool in ("usr/bin/slirp4netns", "usr/sbin/nft"):
        (tmp_path / tool).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / tool).touch()
    assert LabRuntime(lab, True, None,  # noqa: FBT003
                      {}, tmp_path, tmp_path / "s").lab.internet is True
    walled, _ = parse_labfile(_HELLO.replace("10.20.0.10/24", "10.20.0.1/24"))  # pc holds .1: no gateway
    assert LabRuntime(walled, True, None,  # noqa: FBT003
                       {}, tmp_path, tmp_path / "s").lab.internet is False
