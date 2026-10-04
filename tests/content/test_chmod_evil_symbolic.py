"""Tier1: chmod-evil's silent stage -- passes on a SYMBOLIC chmod of the file (the current command)."""
import subprocess
from pathlib import Path

import pytest

_SYM = Path(__file__).resolve().parents[2] / "content" / "tasks" / "chmod-evil" / "hp" / "symbolic"
_FILE = "/home/student/target/test1"


def _symbolic(command: str) -> bool:
    # The engine runs a check script as `<script> <student command> <args from the Taskfile>`.
    return subprocess.run(["sh", str(_SYM), command, _FILE], check=False).returncode == 0


@pytest.mark.tier1
@pytest.mark.parametrize("command", [
    "chmod +x target/test1", "chmod a+x test1", "sudo chmod -v ugo+x /home/student/target/test1",
    "chmod +x target/test*", "chmod u=x,go=x target/test1", "chmod -R a+X target",
    "chmod -x target/test1",
])
def test_symbolic_chmod_of_the_file_passes(command):
    assert _symbolic(command)


@pytest.mark.tier1
@pytest.mark.parametrize("command", [
    "chmod 111 target/test1", "chmod 0111 test1", "chmod -R 111 target", "chmod 111 target/test*",
    "chmod +x target/test2", "ls -l target/test1", "", "stat target/test1",
])
def test_digits_other_files_and_other_commands_do_not(command):
    assert not _symbolic(command)
