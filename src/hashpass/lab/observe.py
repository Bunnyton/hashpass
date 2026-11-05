"""
A lab's observer (spec 2026-11-05): the status feed, the control channel, the browser view.

The mirror itself is wiring (wire.py). Here lives what the host keeps running beside the lab:
- `status_doc` -- the machines, their links and counters, written as /run/hp-lab/status.json;
- `Control` + `ControlServer` -- HTTP over /run/hp-lab/control.sock: the observer asks, the host
  checks the Labfile's `control` and runs `ip`/`tc` in the switch (only names from the lab model
  ever reach a command line);
- `ViewForward` -- 127.0.0.1:<port> on the student's computer piped to a machine's `view` port.
"""
from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING

from hashpass.lab.model import OBSERVER_IFACE
from hashpass.lab.wire import port_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from hashpass.lab.model import Lab

STATUS_VERSION = 1
STATUS_FILE = "status.json"
CONTROL_SOCK = "control.sock"
MAX_DELAY_MS = 5000
MAX_LOSS_PCT = 100
_MAX_BODY = 4096
_COUNTERS = ("rx_bytes", "rx_packets", "tx_bytes", "tx_packets")
_NET_DEV_FIELDS = 16          # a /proc/net/dev line: 8 receive + 8 transmit numbers
_BUF = 65536
_CONNECT_TRIES = 20      # x _CONNECT_WAIT
_CONNECT_WAIT = 0.25

_HTTP_OK = 200
_HTTP_BAD = 400
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_TOO_LARGE = 413
_HTTP_FAILED = 500


def parse_net_dev(text: str) -> dict[str, dict[str, int]]:
    """Parse /proc/net/dev: iface -> rx/tx bytes and packets."""
    out: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        name, sep, rest = line.partition(":")
        nums = rest.split()
        if not sep or len(nums) != _NET_DEV_FIELDS or not all(n.isdigit() for n in nums):
            continue
        out[name.strip()] = {"rx_bytes": int(nums[0]), "rx_packets": int(nums[1]),
                             "tx_bytes": int(nums[8]), "tx_packets": int(nums[9])}
    return out


def status_doc(lab: Lab, *, states: dict[str, str],  # noqa: PLR0913
               counters: dict[str, dict[str, dict[str, int]]],
               links: dict[tuple[str, str], str], netem: dict[tuple[str, str], tuple[int, int]],
               views: dict[str, int], ts: float) -> dict:
    """
    Return the status feed (spec 2026-11-05 §4): networks, machines with their ifaces, the observer.

    `states`: machine -> running|starting (missing = stopped); `counters`: machine -> its
    /proc/net/dev; `links`/`netem`: what the control channel set, by (machine, net).
    """
    gws = lab.gateways()
    subnets = {n.net: str(ipaddress.ip_interface(n.addr).network) for m in lab.machines for n in m.nets}
    machines = []
    for m in lab.machines:
        dev = counters.get(m.name, {})
        ifaces = []
        for k, n in enumerate(m.nets):
            name = f"eth{k}"
            delay, loss = netem.get((m.name, n.net), (0, 0))
            nums = dev.get(name, {})
            ifaces.append({"iface": name, "net": n.net, "addr": n.addr,
                           "link": links.get((m.name, n.net), "up"),
                           "netem": {"delay_ms": delay, "loss_pct": loss},
                           **{c: nums.get(c, 0) for c in _COUNTERS}})
        machines.append({"name": m.name, "console": m.console, "observer": bool(m.observe),
                         "state": states.get(m.name, "stopped"), "ifaces": ifaces})
    obs = lab.observer
    return {
        "version": STATUS_VERSION, "lab": lab.name, "ts": ts,
        "networks": [{"name": net, "subnet": subnets[net], "gateway": gws.get(net)}
                     for net in lab.networks],
        "machines": machines,
        "observer": None if obs is None else {"name": obs.name, "iface": OBSERVER_IFACE,
                                              "networks": list(obs.observe),
                                              "control": list(obs.control)},
        "views": [{"machine": name, "port": port} for name, port in views.items()],
    }


def write_status(directory: Path, doc: dict) -> None:
    """Write status.json atomically: a reader never sees half a document."""
    tmp = directory / f".{STATUS_FILE}.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o644)
    tmp.replace(directory / STATUS_FILE)


class _RequestError(Exception):
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


def _int_field(body: dict, key: str, top: int) -> int:
    value = body.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= top:
        raise _RequestError(_HTTP_BAD, f"{key}: целое число 0…{top}")
    return value


class Control:
    """The control channel's logic: check a request against the Labfile, run it in the switch."""

    def __init__(self, lab: Lab, execute: Callable[[str], None],
                 status: Callable[[], dict] | None = None) -> None:
        """`execute` runs one sh line in the switch's netns (raises on failure)."""
        self.lab = lab
        self.execute = execute
        self.status = status or dict
        obs = lab.observer
        self.allowed = set(obs.control) if obs is not None else set()
        self.links: dict[tuple[str, str], str] = {}
        self.netem: dict[tuple[str, str], tuple[int, int]] = {}
        self._lock = threading.Lock()

    def _port(self, body: dict) -> tuple[str, str, str]:
        machine, net = body.get("machine"), body.get("net")
        m = next((m for m in self.lab.machines if m.name == machine), None)
        if m is None:
            raise _RequestError(_HTTP_NOT_FOUND, f"в стенде нет машины {machine!r}")
        k = next((k for k, n in enumerate(m.nets) if n.net == net), None)
        if k is None:
            raise _RequestError(_HTTP_NOT_FOUND, f"машина {m.name} не подключена к сети {net!r}")
        return m.name, m.nets[k].net, port_name(self.lab, m.name, k)

    def _link(self, body: dict) -> None:
        machine, net, port = self._port(body)
        state = body.get("state")
        if state not in {"up", "down"}:
            raise _RequestError(_HTTP_BAD, "state: up или down")
        self.execute(f"ip link set {port} {state}")
        self.links[machine, net] = state

    def _netem(self, body: dict) -> None:
        machine, net, port = self._port(body)
        delay = _int_field(body, "delay_ms", MAX_DELAY_MS)
        loss = _int_field(body, "loss_pct", MAX_LOSS_PCT)
        if delay == 0 and loss == 0:
            self.execute(f"tc qdisc del dev {port} root 2>/dev/null || true")
            self.netem.pop((machine, net), None)
        else:
            self.execute(f"tc qdisc replace dev {port} root netem delay {delay}ms loss {loss}%")
            self.netem[machine, net] = (delay, loss)

    def _body(self, op: str, raw: bytes) -> dict:
        if op not in self.allowed:
            raise _RequestError(_HTTP_FORBIDDEN, f"операция {op} не разрешена (строка control в Labfile)")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise _RequestError(_HTTP_BAD, "тело запроса — не JSON") from None
        if not isinstance(body, dict):
            raise _RequestError(_HTTP_BAD, "тело запроса — JSON-объект")
        return body

    def handle(self, method: str, path: str, raw: bytes) -> tuple[int, dict]:
        """Answer one request: (HTTP code, JSON body)."""
        path = path.split("?", 1)[0].rstrip("/") or "/"
        if method == "GET" and path == "/status":
            return _HTTP_OK, self.status()
        ops = {"/link": ("link", self._link), "/netem": ("netem", self._netem)}
        if method != "POST" or path not in ops:
            return _HTTP_NOT_FOUND, {"ok": False, "error": f"нет запроса {method} {path}: "
                                     "GET /status, POST /link, POST /netem"}
        op, run = ops[path]
        try:
            body = self._body(op, raw)
            with self._lock:
                run(body)
        except _RequestError as e:
            return e.code, {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 -- the helper failed: tell the observer, keep serving
            return _HTTP_FAILED, {"ok": False, "error": f"не удалось: {e}"}
        return _HTTP_OK, {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    server: _UnixHTTPServer
    protocol_version = "HTTP/1.0"      # one request per connection
    timeout = 5                        # a stalled client does not hold a thread

    def address_string(self) -> str:
        return "observer"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def _answer(self) -> None:
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = -1
        if size < 0 or size > _MAX_BODY or self.headers.get("Transfer-Encoding"):
            code, body = _HTTP_TOO_LARGE, {"ok": False, "error": f"тело — до {_MAX_BODY} байт, с Content-Length"}
        else:
            raw = self.rfile.read(size) if size else b""
            code, body = self.server.control.handle(self.command, self.path, raw)
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _answer  # noqa: N815
    do_POST = _answer  # noqa: N815


class _UnixHTTPServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    control: Control

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        conn, _ = self.socket.accept()
        return conn, ("observer", 0)     # BaseHTTPRequestHandler wants an address pair


class ControlServer:
    """The control channel: HTTP/1.0 on a unix socket (0666: the observer's student may ask too)."""

    def __init__(self, path: Path, control: Control) -> None:
        """Bind nothing yet: `start` opens the socket."""
        self.path = Path(path)
        self.control = control
        self._server: _UnixHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Open the socket and serve in a background thread."""
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        server = _UnixHTTPServer(str(self.path), _Handler)
        server.control = self.control
        os.chmod(self.path, 0o666)  # noqa: PTH101, S103 -- only the observer has it mounted
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and remove the socket. Idempotent."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def _pump(src: socket.socket, dst: socket.socket) -> None:
    with contextlib.suppress(OSError):
        while data := src.recv(_BUF):
            dst.sendall(data)
    with contextlib.suppress(OSError):
        dst.shutdown(socket.SHUT_WR)


class ViewForward:
    """127.0.0.1:<port> on the host, each connection piped to a machine's view relay socket."""

    def __init__(self, target: Path, preferred: int) -> None:
        """`preferred`: the same number as the machine's port when free (0 = any)."""
        self.target = Path(target)
        self.preferred = preferred
        self.port = 0
        self._sock: socket.socket | None = None
        self._stop = threading.Event()

    def _bind(self) -> socket.socket:
        for port in dict.fromkeys((self.preferred, 0)):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                s.close()
                continue
            return s
        msg = "нет свободного порта для просмотра"
        raise RuntimeError(msg)

    def start(self) -> None:
        """Listen and accept in a background thread."""
        self._sock = self._bind()
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self._stop.is_set() and self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        conn.settimeout(None)
        up = None
        for _ in range(_CONNECT_TRIES):     # the relay may still be coming up with the lab
            up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                up.connect(str(self.target))
                break
            except OSError:
                up.close()
                up = None
                if self._stop.wait(_CONNECT_WAIT):
                    break
        if up is None:
            conn.close()
            return
        back = threading.Thread(target=_pump, args=(up, conn), daemon=True)
        back.start()
        _pump(conn, up)
        back.join()
        conn.close()
        up.close()

    def stop(self) -> None:
        """Stop listening (open connections end with the relay). Idempotent."""
        self._stop.set()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None
