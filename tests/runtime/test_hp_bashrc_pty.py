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
    child = pexpect.spawn("bash", ["--rcfile", str(_RC), "-i"], env=env, encoding="utf-8",
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
