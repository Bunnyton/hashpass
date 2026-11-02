"""Tier1: a change under src/hashpass/runtime/ must come with a base-stamp bump."""
import hashlib
from pathlib import Path

import pytest

from hashpass.image.base import runtime_stamp

_RUNTIME = Path(__file__).resolve().parents[2] / "src" / "hashpass" / "runtime"

# Bump BOTH when the runtime tree changes: the stamp (etc/hp-base-version) and this hash.
# Without a bump, `push base` finds the tag unchanged and students never get the new runtime.
_STAMP = "50"
_TREE_SHA256 = "7d568caa3cc00d0db844151f3ea3bbbb119df9b5271f23f2aeb597dcaacf17d8"


def _tree_hash() -> str:
    h = hashlib.sha256()
    for f in sorted(_RUNTIME.rglob("*")):
        if f.is_file() and f.name != "hp-base-version":
            h.update(str(f.relative_to(_RUNTIME)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


@pytest.mark.tier1
def test_runtime_tree_change_requires_a_stamp_bump():
    assert runtime_stamp() == _STAMP, "runtime stamp changed: update _STAMP and _TREE_SHA256 here"
    assert _tree_hash() == _TREE_SHA256, (
        "src/hashpass/runtime/ changed: bump etc/hp-base-version, then update _STAMP/_TREE_SHA256")
