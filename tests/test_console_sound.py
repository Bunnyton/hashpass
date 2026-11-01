"""Tier1: the console hears the host's sound server (user 2026-11-01: «музыку пробрось» -- moria's video)."""
import socket
from pathlib import Path

import pytest

from hashpass.cli import _sound_args


def _sock(path: Path) -> socket.socket:
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    return s


@pytest.mark.tier1
def test_the_hosts_pulse_socket_goes_in_where_the_image_looks(tmp_path: Path) -> None:
    s = _sock(tmp_path / "run" / "pulse" / "native")
    try:
        args = _sound_args({"XDG_RUNTIME_DIR": str(tmp_path / "run"), "HOME": str(tmp_path / "home")})
    finally:
        s.close()
    assert args == [f"--bind={tmp_path / 'run' / 'pulse' / 'native'}:/run/hp-sound/native"]


@pytest.mark.tier1
def test_pulse_server_and_cookie_are_honoured(tmp_path: Path) -> None:
    s = _sock(tmp_path / "elsewhere" / "pa.sock")
    cookie = tmp_path / "home" / ".config" / "pulse" / "cookie"
    cookie.parent.mkdir(parents=True)
    cookie.write_bytes(b"\0" * 256)
    try:
        args = _sound_args({"PULSE_SERVER": f"unix:{tmp_path / 'elsewhere' / 'pa.sock'}",
                            "HOME": str(tmp_path / "home")})
    finally:
        s.close()
    assert args == [f"--bind={tmp_path / 'elsewhere' / 'pa.sock'}:/run/hp-sound/native",
                    f"--bind-ro={cookie}:/run/hp-sound/cookie"]


@pytest.mark.tier1
def test_no_sound_server_no_binds(tmp_path: Path) -> None:
    (tmp_path / "pulse").mkdir()
    (tmp_path / "pulse" / "native").write_text("not a socket")
    assert _sound_args({"XDG_RUNTIME_DIR": str(tmp_path)}) == []
    assert _sound_args({}) == []
    assert _sound_args({"PULSE_SERVER": "tcp:10.0.0.1"}) == []
