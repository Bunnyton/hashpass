"""Tier1: `accept cmd` names the command the student RAN (anchored), and `ok` needs exit 0."""
import pytest

from hashpass.taskrun import _accepted_by_cmd
from hashpass.taskstore import StageMeta


def _stage(*patterns: str, ok: bool = False) -> StageMeta:
    return StageMeta(message="m", neutral=(), check=None, on_enter=(), on_pass=(),
                     acceptance="command", accept_cmds=patterns, accept_ok=ok)


@pytest.mark.tier1
@pytest.mark.parametrize(("pattern", "command", "expected"), [
    ("cmatrix", "cmatrix", True),
    ("cmatrix", "sudo cmatrix -s", True),
    ("cmatrix", "ls | cmatrix", True),                 # any pipeline segment
    ("cmatrix", "dpkg -s cmatrix", False),             # mentions it, does not run it
    ("cmatrix", "ls cmatrix_2.0-3_amd64.deb", False),
    ("cmatrix", "rm cmatrix*.deb", False),
    ("sl", "sl -l", True),
    ("sl", "sleep 600 &", False),                      # word boundary, not a prefix
    ("ls --help", "ls --help | head", True),
    ("ls --help", "ls --hepl", False),
    ("man man", "man man", True),
    ("apt update", "sudo apt update", True),
    ("apt-get update", "sudo -E apt-get update", True),
    ("apt install ./", "sudo apt install ./cmatrix_2.0-3_amd64.deb", True),   # `/` ends: prefix
    ("dpkg -i", "sudo dpkg -i ./x.deb", True),
    ("dpkg -i", "dpkg -install", False),
    ("grep -r ERROR", "sudo grep -r ERROR /var/log", True),
])
def test_accept_cmd_is_anchored_on_the_command_actually_run(pattern, command, expected):
    assert _accepted_by_cmd(_stage(pattern), command, None) is expected


@pytest.mark.tier1
def test_accept_cmd_ok_requires_exit_zero_but_tolerates_an_unknown_status():
    ok = _stage("cmatrix", ok=True)
    assert _accepted_by_cmd(ok, "cmatrix", 0) is True
    assert _accepted_by_cmd(ok, "cmatrix", 127) is False       # died on a missing library
    assert _accepted_by_cmd(ok, "cmatrix", None) is True        # older console: status unknown
    plain = _stage("telnet")
    assert _accepted_by_cmd(plain, "telnet telehack.com", 1) is True   # no `ok`: failure counts
