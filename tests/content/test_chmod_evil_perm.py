"""Tier1: chmod-evil's background rule -- the mode must be right AND set by a symbolic chmod."""
import os
import subprocess
from pathlib import Path

import pytest

_PERM = Path(__file__).resolve().parents[2] / "content" / "tasks" / "chmod-evil" / "hp" / "perm"


def _perm(tmp_path: Path, mode: int, history: list[str], want: str = "111") -> bool:
    target = tmp_path / "target"
    target.mkdir(exist_ok=True)
    f = target / "test1"
    f.write_text("x", encoding="utf-8")
    f.chmod(mode)
    hist = tmp_path / "history"
    hist.write_text("".join(h + "\n" for h in history), encoding="utf-8")
    env = {**os.environ, "HP_HISTORY": str(hist)}
    return subprocess.run(["sh", str(_PERM), history[-1] if history else "", str(f), want], env=env, check=False).returncode == 0


@pytest.mark.tier1
@pytest.mark.parametrize("history", [
    ["chmod +x target/test1"],
    ["cd target", "chmod a+x test1"],
    ["chmod 111 target/test1", "chmod a-x target/test1", "chmod +x target/test1"],   # redone by +/-
    ["sudo chmod -v ugo+x /home/student/target/test1"],
    ["chmod +x target/test*"],                                                       # a glob
    ["chmod 755 target/test3", "chmod +x target/test1"],                            # other file
])
def test_symbolic_last_chmod_with_the_right_mode_passes(tmp_path, history):
    assert _perm(tmp_path, 0o111, history)


@pytest.mark.tier1
@pytest.mark.parametrize("history", [
    ["chmod 111 target/test1"],
    ["cd target && chmod 0111 test1"],
    ["chmod +x target/test1", "chmod 111 target/test1"],                            # last is digits
    ["chmod -R 111 target"],                                                         # the whole dir
    ["chmod 111 target/test*"],
    [],                      # the background FS poll can beat the history write: not yet explained
    ["ls -l target"],
])
def test_numeric_last_chmod_is_silently_refused(tmp_path, history):
    assert not _perm(tmp_path, 0o111, history)


@pytest.mark.tier1
def test_wrong_mode_fails_whatever_the_history(tmp_path):
    assert not _perm(tmp_path, 0o100, ["chmod u+x target/test1"])
