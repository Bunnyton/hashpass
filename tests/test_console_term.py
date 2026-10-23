"""Tier1: the console's TERM is one the task's image can describe (user 2026-10-23: cmatrix in kitty)."""
from pathlib import Path

import pytest

from hashpass.cli import _container_term


def _terminfo(root: Path, base: str, name: str) -> None:
    path = root / base / name[0] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x1a\x01")


@pytest.mark.tier1
def test_a_terminal_the_image_knows_goes_in_as_is(tmp_path: Path) -> None:
    _terminfo(tmp_path, "usr/share/terminfo", "xterm-256color")
    _terminfo(tmp_path, "lib/terminfo", "linux")
    assert _container_term(tmp_path, "xterm-256color") == "xterm-256color"
    assert _container_term(tmp_path, "linux") == "linux"


@pytest.mark.tier1
def test_kitty_and_other_unknown_terminals_fall_back_to_xterm_256color(tmp_path: Path) -> None:
    _terminfo(tmp_path, "usr/share/terminfo", "xterm-256color")
    assert _container_term(tmp_path, "xterm-kitty") == "xterm-256color"
    assert _container_term(tmp_path, "") == "xterm-256color"
    assert _container_term(tmp_path, "../../etc/passwd") == "xterm-256color"


@pytest.mark.tier1
def test_the_hosts_own_terminfo_goes_in_so_keys_match(tmp_path: Path) -> None:
    """Mc on kitty/alacritty: plain arrows dead (no kcuu1 for an unknown TERM), shift-arrows alive."""
    from hashpass.cli import _console_term  # noqa: PLC0415
    rootfs, host = tmp_path / "root", tmp_path / "kitty"
    _terminfo(rootfs, "usr/share/terminfo", "xterm-256color")
    _terminfo(host, "", "xterm-kitty")
    term, args = _console_term(rootfs, {"TERM": "xterm-kitty", "TERMINFO": str(host)})
    assert term == "xterm-kitty"
    assert args == [f"--bind-ro={host / 'x' / 'xterm-kitty'}:/etc/terminfo/x/xterm-kitty"]
    assert _console_term(rootfs, {"TERM": "xterm-256color"}) == ("xterm-256color", [])
    assert _console_term(rootfs, {"TERM": "nowhere-term", "HOME": str(tmp_path)}) == ("xterm-256color", [])
    hexed = tmp_path / "mac"                                      # macOS: 78/xterm-kitty
    (hexed / "78").mkdir(parents=True)
    (hexed / "78" / "xterm-kitty").write_bytes(b"\x1a\x01")
    assert _console_term(rootfs, {"TERM": "xterm-kitty", "TERMINFO_DIRS": f"/nope:{hexed}"})[0] == "xterm-kitty"
