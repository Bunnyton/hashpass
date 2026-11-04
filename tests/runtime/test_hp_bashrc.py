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


@pytest.mark.tier1
def test_hp_bashrc_puts_the_sbin_dirs_on_path_for_every_user(tmp_path):
    # User (2026-10-12) asked for net-tools in the base; `ifconfig` lives in /usr/sbin, which
    # Debian keeps out of a regular user's PATH -- the student got «command not found».
    out = subprocess.run(
        ["bash", "-i", "-c", f'. {_RC}; printf %s "$PATH"'],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TERM": "dumb"},
        capture_output=True, text=True, check=True).stdout
    assert {"/usr/sbin", "/sbin"} <= set(out.split(":"))


@pytest.mark.tier1
def test_the_hooks_survive_a_path_the_student_wiped():
    """
    The console's hooks call their tools by full path: a student's PATH must not cut grading.

    bash-path, 2026-11-04: `PATH=~/tools/bin` broke `date`, `base64`, `hp-io` in the hooks -- no
    command reached grading, no hint could come. A PATH of the hooks' own would flush bash's
    `hash` on every command (which-path teaches `hash -r`), so: full paths.
    """
    code = [ln.split("#", 1)[0] for ln in _RC.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")]
    import re  # noqa: PLC0415
    bare = re.compile(r"(?:\$\(|\|\s*|^\s*|;\s*|&&\s*|\|\|\s*)(date|base64|sed|tail|awk|cat|hp-io)\b")
    offenders = [ln.strip() for ln in code if bare.search(ln) and "alias " not in ln]
    assert not offenders, "\n".join(offenders)
    hp_io = (_RC.parents[1] / "usr" / "local" / "bin" / "hp-io").read_text(encoding="utf-8")
    assert "\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n" in hp_io
