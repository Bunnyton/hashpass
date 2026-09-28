"""Tier1: the console shell config (`/etc/hp-bashrc`) as students and root actually get it."""
import os
import subprocess
from pathlib import Path

import pytest

_RC = Path(__file__).resolve().parents[2] / "src" / "hashpass" / "runtime" / "etc" / "hp-bashrc"


@pytest.mark.tier1
def test_hp_bashrc_puts_the_games_dirs_on_path_for_every_user(tmp_path):
    # `su - root` gives login.defs' ENV_SUPATH, which has no /usr/games -- so `sl`
    # (installed at /usr/games/sl) was "command not found" for root-run tasks while
    # `apt remove sl` happily worked. The rc file must add the games dirs itself, once.
    env = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
           "HOME": str(tmp_path)}
    env.pop("HP_PORT", None)
    out = subprocess.run(["bash", "--rcfile", str(_RC), "-ic", 'printf %s "$PATH"'],
                         capture_output=True, text=True, env=env, check=True, timeout=20).stdout
    parts = out.strip().split(":")
    assert "/usr/games" in parts and "/usr/local/games" in parts
    assert parts.count("/usr/games") == 1                                  # idempotent
