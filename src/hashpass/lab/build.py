"""
Build a lab: its machines' images in, one task ref out (spec 2026-11-02 §1а).

The lab ref is an image whose parent is the console's image and whose layer holds only
`/.hp-nodes/<node>/` -- each node's image chain merged into one delta over the base -- and
`/.hp-nodes/lab.json`. To the pool it is an ordinary task image: nothing changes server-side.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from typing import TYPE_CHECKING

from hashpass.imagestore.resolve import resolve_lowers
from hashpass.lab.config import LAB_JSON, NODES_DIR, lab_to_dict

if TYPE_CHECKING:
    from pathlib import Path

    from hashpass.imagestore.store import ImageStore
    from hashpass.lab.model import Lab


def flatten_into(chain: list[Path], dest: Path) -> None:
    """Merge an image chain (topmost first) into `dest`, bottom-up; overlay whiteouts carry over."""
    dest.mkdir(parents=True, exist_ok=True)
    for layer in reversed(chain):
        subprocess.run(["sudo", "rsync", "-a", f"--exclude=/{NODES_DIR}", f"{layer}/", f"{dest}/"],
                       check=True)


def stage_nodes(lab: Lab, machine_refs: dict[str, str], store: ImageStore, workdir: Path, *,
                hosts: bool) -> tuple[Path, str]:
    """
    Lay out the lab layer's `/.hp-nodes` under `workdir`; return (dir, cache key).

    The key folds lab.json with every node image's content id, so a rebuilt machine rebuilds the lab.
    """
    out = workdir / "lab-layer"
    nodes = out / NODES_DIR
    nodes.mkdir(parents=True, exist_ok=True)
    ids = []
    for node in lab.nodes:
        ref = machine_refs[node.name]
        flatten_into(resolve_lowers((ref,), store), nodes / node.name)
        img = store.get(ref)
        ids.append(f"{node.name}={ref}@{img.build_key or img.pool_digest or ''}")
    text = json.dumps(lab_to_dict(lab, hosts=hosts), ensure_ascii=False, indent=1, sort_keys=True)
    (nodes / LAB_JSON).write_text(text + "\n", encoding="utf-8")
    key = hashlib.sha256((text + "\0" + "\0".join(ids)).encode()).hexdigest()
    return out, key
