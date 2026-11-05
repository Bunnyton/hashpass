"""Lab observer (spec 2026-11-05): `observe`/`view`/`control`, the mirror, the status feed, control."""
import json
import socket
import threading

import pytest

from hashpass.lab.config import lab_from_dict, lab_to_dict
from hashpass.lab.model import Lab
from hashpass.lab.observe import (
    Control,
    ControlServer,
    ViewForward,
    parse_net_dev,
    status_doc,
)
from hashpass.lab.parse import parse_labfile
from hashpass.lab.wire import port_name, wire_script

_VIEW = """\
lab v:1
machine pc
  console
  build pc
  net lan 10.20.0.10/24
machine web
  build web
  net lan 10.20.0.20/24
  net dmz 10.30.0.20/24
machine mon
  build mon
  net lan 10.20.0.30/24
  observe all
  view 8080
  control link, netem
say "x"
stage
  solve true
"""


def _lab(text: str = _VIEW) -> Lab:
    return parse_labfile(text)[0]


# ---------------------------------------------------------------- Labfile


@pytest.mark.tier1
def test_observe_view_control_parse() -> None:
    lab = _lab()
    mon = lab.machines[2]
    assert mon.observe == ("lan", "dmz")            # `all` = every network of the lab
    assert mon.view == 8080  # noqa: PLR2004
    assert mon.control == ("link", "netem")
    assert lab.observer is mon
    assert lab.machines[0].observe == () and lab.machines[0].view is None


@pytest.mark.tier1
def test_observe_named_networks_and_no_net_observer() -> None:
    text = _VIEW.replace("  net lan 10.20.0.30/24\n  observe all", "  observe dmz")
    mon = _lab(text).machines[2]
    assert mon.observe == ("dmz",) and mon.nets == ()


@pytest.mark.tier1
def test_no_observe_means_no_observer() -> None:
    lab = _lab(_VIEW.replace("  observe all\n", "").replace("  control link, netem\n", ""))
    assert lab.observer is None
    assert lab.machines[2].view == 8080           # view works on any machine  # noqa: PLR2004


@pytest.mark.tier1
@pytest.mark.parametrize(("old", "new", "match"), [
    ("  observe all", "  observe wan", "сети wan"),
    ("  control link, netem", "  control link, power", "power"),
    ("  view 8080", "  view 0", "порт"),
    ("  view 8080", "  view http", "порт"),
    ("  view 8080", "  view 8080\n  view 8081", "view"),
    ("  observe all\n", "", "control"),            # control without observe
])
def test_observe_errors(old: str, new: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_labfile(_VIEW.replace(old, new))


@pytest.mark.tier1
def test_only_one_observer() -> None:
    text = _VIEW.replace("  net dmz 10.30.0.20/24\n", "  net dmz 10.30.0.20/24\n  observe lan\n")
    with pytest.raises(ValueError, match="наблюдатель"):
        parse_labfile(text)


@pytest.mark.tier1
def test_lab_json_keeps_observe_and_old_json_has_none() -> None:
    lab = _lab()
    back, _ = lab_from_dict(json.loads(json.dumps(lab_to_dict(lab, hosts=True))))
    assert back.machines[2].observe == ("lan", "dmz")
    assert back.machines[2].view == 8080  # noqa: PLR2004
    assert back.machines[2].control == ("link", "netem")
    old = lab_to_dict(lab, hosts=True)
    for m in old["machines"]:
        for key in ("observe", "view", "control"):
            m.pop(key, None)
    assert lab_from_dict(old)[0].observer is None


# ---------------------------------------------------------------- the mirror


@pytest.mark.tier1
def test_wire_mirrors_every_port_once_but_the_observers_own() -> None:
    lab = _lab()
    script = wire_script(lab).splitlines()
    assert "ip link add vmon type veth peer name mon0 netns mon" in script
    assert "ip -n mon link set mon0 arp off up" in script
    assert any("disable_ipv6=1" in s and "mon0" in s for s in script)
    pc, web0, web1, mon = (port_name(lab, "pc", 0), port_name(lab, "web", 0),
                           port_name(lab, "web", 1), port_name(lab, "mon", 0))
    for port in (pc, web0, web1):
        assert f"tc filter add dev {port} ingress matchall action mirred egress mirror dev vmon" in script
    assert not any(f"dev {mon} " in s and "mirred" in s for s in script)   # no feedback loop
    for br in ("br-lan", "br-dmz"):          # the switch's own frames (gateway, internet)
        assert f"tc filter add dev {br} egress matchall action mirred egress mirror dev vmon" in script
    # mirrors go in after the veths they hang on
    first_tc = next(i for i, s in enumerate(script) if s.startswith("tc "))
    last_veth = max(i for i, s in enumerate(script) if "type veth peer name eth" in s)
    assert first_tc > last_veth


@pytest.mark.tier1
def test_wire_mirrors_only_the_observed_networks() -> None:
    lab = _lab(_VIEW.replace("observe all", "observe dmz"))
    script = wire_script(lab)
    assert f"dev {port_name(lab, 'web', 1)} ingress" in script
    assert f"dev {port_name(lab, 'web', 0)} ingress" not in script
    assert f"dev {port_name(lab, 'pc', 0)} ingress" not in script


@pytest.mark.tier1
def test_without_observe_the_wiring_is_unchanged() -> None:
    lab = _lab(_VIEW.replace("  observe all\n", "").replace("  control link, netem\n", ""))
    script = wire_script(lab)
    assert "tc " not in script and "vmon" not in script


# ---------------------------------------------------------------- the status feed


_NET_DEV = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
  eth0:    1744      20    0    0    0     0          0         0      962      11    0    0    0     0       0          0
"""


@pytest.mark.tier1
def test_parse_net_dev() -> None:
    got = parse_net_dev(_NET_DEV)
    assert got["eth0"] == {"rx_bytes": 1744, "rx_packets": 20, "tx_bytes": 962, "tx_packets": 11}
    assert "lo" in got
    assert parse_net_dev("garbage\n") == {}


@pytest.mark.tier1
def test_status_doc() -> None:
    lab = _lab()
    doc = status_doc(lab, states={"pc": "running", "web": "starting"},
                     counters={"web": parse_net_dev(_NET_DEV)},
                     links={("web", "lan"): "down"}, netem={("web", "dmz"): (200, 10)},
                     views={"mon": 8080}, ts=5.0)
    assert doc["version"] == 1 and doc["lab"] == "v" and doc["ts"] == 5.0  # noqa: PLR2004
    assert doc["networks"][0] == {"name": "lan", "subnet": "10.20.0.0/24", "gateway": "10.20.0.1"}
    pc, web, mon = doc["machines"]
    assert pc["console"] is True and pc["state"] == "running"
    assert web["state"] == "starting" and mon["state"] == "stopped" and mon["observer"] is True
    eth0, eth1 = web["ifaces"]
    assert eth0 == {"iface": "eth0", "net": "lan", "addr": "10.20.0.20/24", "link": "down",
                    "netem": {"delay_ms": 0, "loss_pct": 0},
                    "rx_bytes": 1744, "rx_packets": 20, "tx_bytes": 962, "tx_packets": 11}
    assert eth1["netem"] == {"delay_ms": 200, "loss_pct": 10} and eth1["rx_bytes"] == 0
    assert doc["observer"] == {"name": "mon", "iface": "mon0", "networks": ["lan", "dmz"],
                               "control": ["link", "netem"]}
    assert doc["views"] == [{"machine": "mon", "port": 8080}]
    json.dumps(doc)


# ---------------------------------------------------------------- control


def _control(text: str = _VIEW) -> tuple[Control, list[str], Lab]:
    ran: list[str] = []
    lab = _lab(text)
    ctl = Control(lab, execute=ran.append)
    return ctl, ran, lab


@pytest.mark.tier1
def test_control_link_down_and_up() -> None:
    ctl, ran, lab = _control()
    code, body = ctl.handle("POST", "/link", b'{"machine":"web","net":"dmz","state":"down"}')
    assert (code, body) == (200, {"ok": True})
    assert ran == [f"ip link set {port_name(lab, 'web', 1)} down"]
    assert ctl.links == {("web", "dmz"): "down"}
    ctl.handle("POST", "/link", b'{"machine":"web","net":"dmz","state":"up"}')
    assert ran[-1].endswith(" up") and ctl.links == {("web", "dmz"): "up"}


@pytest.mark.tier1
def test_control_netem_and_clear() -> None:
    ctl, ran, lab = _control()
    port = port_name(lab, "pc", 0)
    code, _ = ctl.handle("POST", "/netem", b'{"machine":"pc","net":"lan","delay_ms":200,"loss_pct":10}')
    assert code == 200  # noqa: PLR2004
    assert ran == [f"tc qdisc replace dev {port} root netem delay 200ms loss 10%"]
    assert ctl.netem == {("pc", "lan"): (200, 10)}
    ctl.handle("POST", "/netem", b'{"machine":"pc","net":"lan","delay_ms":0,"loss_pct":0}')
    assert ran[-1] == f"tc qdisc del dev {port} root 2>/dev/null || true"
    assert ctl.netem == {}


@pytest.mark.tier1
@pytest.mark.parametrize(("path", "body", "code"), [
    ("/link", b'{"machine":"db","net":"lan","state":"down"}', 404),
    ("/link", b'{"machine":"pc","net":"dmz","state":"down"}', 404),
    ("/link", b'{"machine":"pc","net":"lan","state":"off; reboot"}', 400),
    ("/link", b"not json", 400),
    ("/netem", b'{"machine":"pc","net":"lan","delay_ms":"1; rm -rf /","loss_pct":0}', 400),
    ("/netem", b'{"machine":"pc","net":"lan","delay_ms":99999,"loss_pct":0}', 400),
    ("/netem", b'{"machine":"pc","net":"lan","delay_ms":10,"loss_pct":101}', 400),
    ("/netem", b'{"machine":"pc","net":"lan","delay_ms":true,"loss_pct":0}', 400),
    ("/power", b"{}", 404),
])
def test_control_rejects(path: str, body: bytes, code: int) -> None:
    ctl, ran, _ = _control()
    got, reply = ctl.handle("POST", path, body)
    assert got == code and reply["ok"] is False and reply["error"]
    assert ran == []


@pytest.mark.tier1
def test_control_only_what_the_labfile_allows() -> None:
    ctl, ran, _ = _control(_VIEW.replace("control link, netem", "control link"))
    code, reply = ctl.handle("POST", "/netem", b'{"machine":"pc","net":"lan","delay_ms":5,"loss_pct":0}')
    assert code == 403 and "netem" in reply["error"] and ran == []  # noqa: PLR2004


@pytest.mark.tier1
def test_control_status_is_always_there() -> None:
    ctl, _, _ = _control(_VIEW.replace("  control link, netem\n", ""))
    ctl.status = lambda: {"version": 1}
    assert ctl.handle("GET", "/status", b"") == (200, {"version": 1})


@pytest.mark.tier1
def test_control_failure_keeps_the_old_state() -> None:
    lab = _lab()

    def boom(_script: str) -> None:
        msg = "nope"
        raise RuntimeError(msg)

    ctl = Control(lab, execute=boom)
    code, reply = ctl.handle("POST", "/link", b'{"machine":"pc","net":"lan","state":"down"}')
    assert code == 500 and "nope" in reply["error"] and ctl.links == {}  # noqa: PLR2004


# ---------------------------------------------------------------- sockets


def _http_unix(path: str, request: bytes) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect(path)
        s.sendall(request)
        chunks = []
        while chunk := s.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.tier1
def test_control_server_speaks_http_on_a_unix_socket(tmp_path) -> None:
    ran: list[str] = []
    ctl = Control(_lab(), execute=ran.append)
    ctl.status = lambda: {"version": 1, "lab": "v"}
    path = tmp_path / "control.sock"
    server = ControlServer(path, ctl)
    server.start()
    try:
        assert path.stat().st_mode & 0o777 == 0o666          # the observer's student may use it  # noqa: PLR2004
        raw = _http_unix(str(path), b"GET /status HTTP/1.0\r\nHost: lab\r\n\r\n")
        head, _, body = raw.partition(b"\r\n\r\n")
        assert b" 200 " in head.split(b"\r\n")[0] and b"application/json" in head
        assert json.loads(body) == {"version": 1, "lab": "v"}
        payload = b'{"machine":"web","net":"lan","state":"down"}'
        raw = _http_unix(str(path), b"POST /link HTTP/1.0\r\nHost: lab\r\nContent-Length: "
                         + str(len(payload)).encode() + b"\r\n\r\n" + payload)
        assert json.loads(raw.partition(b"\r\n\r\n")[2]) == {"ok": True}
        assert len(ran) == 1
        raw = _http_unix(str(path), b"POST /link HTTP/1.0\r\nContent-Length: 999999\r\n\r\n")
        assert b" 413 " in raw.split(b"\r\n")[0] and len(ran) == 1
    finally:
        server.stop()
    assert not path.exists()


@pytest.mark.tier1
def test_view_forward_pipes_tcp_to_a_unix_socket(tmp_path) -> None:
    path = tmp_path / "view.sock"
    backend = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    backend.bind(str(path))
    backend.listen(1)

    def echo() -> None:
        conn, _ = backend.accept()
        with conn:
            data = conn.recv(100)
            conn.sendall(b"echo:" + data)

    t = threading.Thread(target=echo, daemon=True)
    t.start()
    fwd = ViewForward(path, preferred=0)
    fwd.start()
    try:
        assert fwd.port > 0
        with socket.create_connection(("127.0.0.1", fwd.port), timeout=5) as c:
            c.sendall(b"hi")
            assert c.recv(100) == b"echo:hi"
    finally:
        fwd.stop()
        backend.close()


@pytest.mark.tier1
def test_view_forward_takes_the_preferred_port_or_another(tmp_path) -> None:
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen(1)
    busy = taken.getsockname()[1]
    try:
        fwd = ViewForward(tmp_path / "x.sock", preferred=busy)
        fwd.start()
        try:
            assert fwd.port not in (0, busy)
        finally:
            fwd.stop()
    finally:
        taken.close()
