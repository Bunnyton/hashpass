"""
Tier1: one uninstaller -- served by the pool and run by `hashpass uninstall`.

User 2026-10-25: «команду для удаления пропиши».
"""
import os
import subprocess
from pathlib import Path

import pytest

from hashpass import student_cli
from hashpass.uninstall import SCRIPT

_OFFLINE = Path(__file__).resolve().parents[1] / "scripts/offline/installer.sh"


def _run(home: Path, *args: str) -> subprocess.CompletedProcess:
    # stubs first on PATH: the test never stops this machine's real consoles or runs sudo
    stubs = home / "stubs"
    stubs.mkdir(exist_ok=True)
    for name in ("machinectl", "sudo"):
        (stubs / name).write_text("#!/bin/sh\nexit 0\n")
        (stubs / name).chmod(0o755)
    env = {**os.environ, "HOME": str(home), "HASHPASS_HOME": str(home / ".hashpass"),
           "PATH": f"{stubs}:{os.environ['PATH']}"}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, check=False, timeout=60)


@pytest.mark.tier1
def test_the_script_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


@pytest.mark.tier1
def test_without_a_terminal_it_asks_for_yes(tmp_path) -> None:
    (tmp_path / ".local/bin").mkdir(parents=True)
    (tmp_path / ".local/bin/hashpass").write_text("x")
    r = _run(tmp_path)
    if "нет терминала" not in r.stderr:      # a test run from a real terminal has /dev/tty
        pytest.skip("/dev/tty is open here")
    assert r.returncode != 0 and (tmp_path / ".local/bin/hashpass").exists()


@pytest.mark.tier1
def test_it_removes_the_commands_and_the_path_lines(tmp_path) -> None:
    line = 'case ":$PATH:" in *":/x/bin:"*) ;; *) export PATH="/x/bin:$PATH" ;; esac  # hashpass'
    (tmp_path / ".bashrc").write_text(f"alias ll='ls -l'\n\n{line}\n")
    (tmp_path / ".profile").write_text(f"{line}\n")
    for name in ("hashpass", "hashengine"):
        p = tmp_path / ".local/bin" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#!/nonexistent/python3\n")
        p.chmod(0o755)
    (tmp_path / ".local/share/hashpass/python").mkdir(parents=True)
    r = _run(tmp_path, "-y")
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / ".local/bin/hashpass").exists()
    assert not (tmp_path / ".local/bin/hashengine").exists()
    assert not (tmp_path / ".local/share/hashpass").exists()
    assert "# hashpass" not in (tmp_path / ".bashrc").read_text()
    assert "alias ll" in (tmp_path / ".bashrc").read_text()
    assert "hashpass удалён" in r.stdout


@pytest.mark.tier1
def test_hashpass_uninstall_is_a_command() -> None:
    args = student_cli.build_parser().parse_args(["uninstall", "-y"])
    assert args.command == "uninstall" and args.yes


@pytest.mark.tier1
def test_the_offline_installer_refuses_root() -> None:
    text = _OFFLINE.read_text()
    check = text.index('[ "$(id -u)" != 0 ] || die')
    assert "без sudo" in text[check:check + 300]
    assert check < text.index("распаковываю")
    assert 'SUDO=""' not in text
