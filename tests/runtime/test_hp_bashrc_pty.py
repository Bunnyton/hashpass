"""Tier1: drive the real console rc in a pty with a fake hp-io -- what the host actually receives."""
import base64
import os
import stat
from pathlib import Path

import pytest

pexpect = pytest.importorskip("pexpect")

_RC = Path(__file__).resolve().parents[2] / "src" / "hashpass" / "runtime" / "etc" / "hp-bashrc"


def _fake_hp_io(tmp_path: Path) -> Path:
    """Write a stand-in for /usr/local/bin/hp-io that logs every request line and replies nothing."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "hp-io"
    shim.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$HP_IO_LOG"\n', encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return bindir


def _requests(log: Path) -> list[str]:
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        kind, _, rest = line.partition(" ")
        if kind == "cmd":
            out.append("cmd " + base64.b64decode(rest.split(" ")[0]).decode())
        else:
            out.append(kind)
    return out


@pytest.mark.tier1
def test_console_ships_only_the_students_commands(tmp_path):
    # The rc is sourced early (from /etc/bash.bashrc in the image); its DEBUG trap must not turn
    # the rest of the startup files into a phantom first command (an extra «try»), and the host
    # is greeted exactly once.
    log = tmp_path / "hp-io.log"
    log.touch()
    env = {**os.environ, "PATH": f"{_fake_hp_io(tmp_path)}:{os.environ['PATH']}",
           "HP_PORT": "1", "HP_IO_LOG": str(log), "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    _drive_and_check(str(_RC), env, log)


@pytest.mark.tier1
def test_startup_lines_after_the_rc_are_not_a_try(tmp_path):
    # In the image /etc/bash.bashrc sources the rc FIRST and the rest of the startup files
    # (skel ~/.bashrc: aliases, PS1 tweaks, command substitutions) run with the DEBUG trap already
    # installed. None of that may reach the host as a command.
    log = tmp_path / "hp-io.log"
    log.touch()
    rc = tmp_path / "bashrc"
    rc.write_text(f". {_RC}\nalias ls='ls --color=auto'\nHOSTTAG=$(hostname)\n"
                  "[ -f /nonexistent ] && . /nonexistent\ntrue\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{_fake_hp_io(tmp_path)}:{os.environ['PATH']}",
           "HP_PORT": "1", "HP_IO_LOG": str(log), "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    _drive_and_check(str(rc), env, log)


def _drive_and_check(rcfile: str, env: dict, log: Path) -> None:
    child = pexpect.spawn("bash", ["--rcfile", rcfile, "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 100))
    child.expect("❯")
    child.sendline("echo hi")
    child.expect("❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)
    reqs = _requests(log)
    assert reqs[0] == "hello"
    cmds = [r for r in reqs if r.startswith("cmd ")]
    assert cmds == ["cmd echo hi"], reqs                    # no `return`/startup-line phantom
    assert reqs.count("hello") == 1


@pytest.mark.tier1
def test_prompt_gets_a_solved_label_once_the_host_says_so(tmp_path):
    # User (2026-10-04): «в конце когда решили добавь в командную строку label [Решено]».
    log = tmp_path / "hp-io.log"
    log.touch()
    flag = tmp_path / "solved"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "hp-io"
    shim.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$HP_IO_LOG"\n'
                    '[ "$1" = state ] && [ -f "$HP_SOLVED" ] && echo solved\nexit 0\n',
                    encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "HP_PORT": "1",
           "HP_IO_LOG": str(log), "HP_SOLVED": str(flag), "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    child = pexpect.spawn("bash", ["--rcfile", str(_RC), "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 100))
    child.expect("❯")
    child.sendline("echo one")
    child.expect("❯")
    assert "Решено" not in child.before
    flag.touch()                                   # the host now reports the task as done
    child.sendline("echo two")
    child.expect(r"\[Решено\][^\n]*❯")
    child.sendline("echo three")                    # it stays
    child.expect(r"\[Решено\][^\n]*❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)
    assert [r for r in _requests(log) if r.startswith("cmd ")] == [
        "cmd echo one", "cmd echo two", "cmd echo three"]
