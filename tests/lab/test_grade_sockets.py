"""Tier1: a lab's grade server -- one unix socket per machine, requests tagged by machine (spec 2026-11-02)."""
import base64
import socket
import threading
from types import SimpleNamespace

import pytest

from hashpass import cli
from hashpass.taskrun import FeedResult


def _ask(path, line: str) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(path))
        s.sendall(line.encode() + b"\n")
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while data := s.recv(4096):
            chunks.append(data)
    return b"".join(chunks)


@pytest.mark.tier1
def test_each_machine_has_its_socket_and_its_commands_are_tagged(tmp_path, monkeypatch):
    seen: list[dict] = []

    def observe(command, **kw):
        seen.append({"command": command, **kw})
        return FeedResult(advanced=False, stage=0, local_key=None)

    session = SimpleNamespace(progress=SimpleNamespace(), observe=observe, meta=SimpleNamespace(stages=()),
                              render=SimpleNamespace(skip=lambda: False), pause=None)
    monkeypatch.setattr(cli, "current_stage", lambda _p: 0)
    monkeypatch.setattr(cli, "_policy_reply", lambda _s: "a;b;c")
    pc, web = tmp_path / "g" / "pc.sock", tmp_path / "g" / "web.sock"
    stop = threading.Event()
    history: list[dict] = []
    port, thread = cli._grade_server(session, cli._Router(lambda _s: None), lambda: "2026-11-02T10:00:00",  # noqa: SLF001
                                     stop, None, history, sockets={pc: None, web: "web"})
    thread.start()
    try:
        assert 20000 <= port < 40000  # noqa: PLR2004
        assert _ask(pc, "state") == b"\n"
        assert _ask(pc, "policy") == b"a;b;c"
        assert _ask(web, "policy") == b";;"                   # the console's policy is not the machine's
        b64 = base64.b64encode(b"systemctl restart nginx").decode()
        _ask(web, f"cmd {b64}")
        _ask(pc, f"cmd {base64.b64encode(b'curl web').decode()}")
    finally:
        stop.set()
        thread.join(timeout=3)
    assert [(s["command"], s.get("node")) for s in seen] == [("systemctl restart nginx", "web"),
                                                             ("curl web", None)]
    assert history[0]["machine"] == "web" and "machine" not in history[1]
