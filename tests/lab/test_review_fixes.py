"""Tier1: fixes from the labs branch review (2026-11-02)."""
import os
import socket
import threading
from types import SimpleNamespace

import pytest

from hashpass import cli
from hashpass.lab.build import node_ids
from hashpass.lab.runtime import grade_dir


@pytest.mark.tier1
def test_a_machine_saved_from_a_console_still_changes_the_lab_key(tmp_path):
    layer = tmp_path / "layer"
    layer.mkdir()
    imgs = {"me/web:1": SimpleNamespace(build_key=None, pool_digest=None, layer=layer, parents=("me/base:1",)),
            "me/base:1": SimpleNamespace(build_key="k1", pool_digest=None, layer=tmp_path, parents=())}
    store = SimpleNamespace(get=lambda r: imgs[r])
    before = node_ids("web", "me/web:1", store)
    os.utime(layer, ns=(1, 1))                       # the commit wrote a new layer
    assert node_ids("web", "me/web:1", store) != before
    k_a = node_ids("web", "me/web:1", store)
    imgs["me/base:1"].build_key = "k2"               # a rebuilt parent of the machine image
    assert node_ids("web", "me/web:1", store) != k_a


@pytest.mark.tier1
def test_relay_port_is_above_the_ephemeral_range():
    assert cli._LAB_PORT_BASE >= 61000  # noqa: PLR2004, SLF001
    assert cli._LAB_PORT_BASE + cli._LAB_PORT_SPAN <= 65536  # noqa: PLR2004, SLF001


@pytest.mark.tier1
def test_grade_sockets_live_on_a_short_path():
    d = grade_dir()
    try:
        assert len(str(d / "abcdefghijklmno.sock")) < 80  # noqa: PLR2004
    finally:
        d.rmdir()


@pytest.mark.tier1
def test_listeners_close_when_a_later_bind_fails(tmp_path, monkeypatch):
    opened: list[socket.socket] = []
    real = socket.socket

    def track(*a: object, **k: object) -> socket.socket:
        s = real(*a, **k)
        opened.append(s)
        return s

    monkeypatch.setattr(cli.socket, "socket", track)
    good, bad = tmp_path / "a.sock", tmp_path / "missing" / "deep" / ("x" * 120) / "b.sock"
    with pytest.raises(OSError, match=r"too long|No such"):
        cli._grade_listeners({good: None, bad: "web"})  # noqa: SLF001
    assert all(s.fileno() == -1 for s in opened)


@pytest.mark.tier1
def test_an_unstarted_grade_server_can_be_closed(tmp_path):
    stop = threading.Event()
    path = tmp_path / "pc.sock"
    _port, thread = cli._grade_server(SimpleNamespace(), cli._Router(lambda _s: None), lambda: "t",  # noqa: SLF001
                                      stop, None, [], sockets={path: None})
    thread.close_listeners()
    with socket.socket(socket.AF_UNIX) as s, pytest.raises(OSError, match=r"refused|No such"):
        s.connect(str(path))
