"""`hashpass uninstall` and the pool's /uninstall.sh: one script removes what either installer put in."""
import os
from pathlib import Path

SCRIPT = Path(__file__).with_name("uninstall.sh")


def text() -> str:
    """Return the script the pool serves at /uninstall.sh."""
    return SCRIPT.read_text(encoding="utf-8")


def run(*, yes: bool) -> int:
    """Become the script: it deletes the very package (and, offline, the Python) running us."""
    os.execvp("bash", ["bash", str(SCRIPT), *(["-y"] if yes else [])])  # noqa: S606
    return 1   # not reached
