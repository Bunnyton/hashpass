"""
The mask layer: an overlay whiteout for `/.hp-nodes`, laid on top of a lab console's chain.

A whiteout is a 0:0 character device -- only root can make one; the NOPASSWD grant covers `tar`,
so `sudo tar` extracts it from a one-member archive built here. Made once per home, reused.
"""
from __future__ import annotations

import io
import stat
import subprocess
import tarfile
from pathlib import Path

from hashpass.lab.config import NODES_DIR


def _is_whiteout(path: Path) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    return stat.S_ISCHR(st.st_mode) and st.st_rdev == 0


def ensure_mask(directory: Path) -> Path:
    """Return `directory`, holding the `.hp-nodes` whiteout (created on first use)."""
    directory = Path(directory)
    if _is_whiteout(directory / NODES_DIR):
        return directory
    directory.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(NODES_DIR)
        info.type, info.devmajor, info.devminor, info.mode = tarfile.CHRTYPE, 0, 0, 0o000
        tar.addfile(info)
    subprocess.run(["sudo", "tar", "-xpf", "-", "-C", str(directory)], input=buf.getvalue(),
                   check=True, capture_output=True)
    if not _is_whiteout(directory / NODES_DIR):
        msg = f"не удалось создать маску {directory / NODES_DIR}"
        raise RuntimeError(msg)
    return directory


def mask_dir(store_root: Path) -> Path:
    """Where a home keeps its mask: next to the image store."""
    return Path(store_root).parent / "lab-mask"
