"""Tier1: replacing a stored layer never fails on files the user cannot delete."""
import os
import subprocess
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore

_OPEN = 0o755


def _layer(tmp_path: Path, tag: str) -> Path:
    src = tmp_path / f"src-{tag}"
    (src / "home" / "student").mkdir(parents=True)
    (src / "home" / "student" / "f.txt").write_text(tag, encoding="utf-8")
    return src


def _open_all(top: Path) -> None:
    for root, dirs, _files in os.walk(top):
        for d in dirs:
            (Path(root) / d).chmod(_OPEN)


@pytest.mark.tier1
def test_a_new_layer_replaces_one_with_undeletable_files(tmp_path: Path, monkeypatch) -> None:
    # User (2026-10-13, a screenshot): «[Errno 13] Permission denied:
    # '/home/chistborw/.hashpass/images/bunnyton/find-2/1/layer/h…'». The old layer held files of
    # another uid (the container's student, 1000 -- not this user); a plain rmtree of it failed
    # and the new layer never landed. Now the old layer is moved aside first, the new one goes
    # live, and the old one is removed -- via `sudo rsync --delete` when a plain delete fails.
    store = ImageStore(tmp_path / "store")
    store.save("t", "1", _layer(tmp_path, "OLD"), ())
    (store.get("t:1").layer / "home").chmod(0o555)      # «not mine»: its entries cannot go
    calls: list[list[str]] = []
    real = subprocess.run

    def fake_run(argv: list[str], *a: object, **k: object) -> subprocess.CompletedProcess:
        if argv[:2] == ["sudo", "rsync"]:               # sudo is not ours to call in a test
            calls.append(argv)
            _open_all(Path(argv[-1]))
            return real(["rsync", "-a", "--delete", *argv[4:]], *a, **k)
        return real(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        store.save("t", "1", _layer(tmp_path, "NEW"), ())
        layer = store.get("t:1").layer
        assert (layer / "home" / "student" / "f.txt").read_text(encoding="utf-8") == "NEW"
        assert calls, "the stuck old layer is removed with sudo rsync"
        assert not list(layer.parent.glob("layer.old-*"))
    finally:
        _open_all(tmp_path)
