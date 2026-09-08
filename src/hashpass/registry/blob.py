"""Blob (tar) pack/unpack for HTTP transfer: images (meta + layer/) and tasks (bundle/hp/meta)."""
import io
import json
import tarfile
import tempfile
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage


def pack_image(img: StoredImage) -> bytes:
    """Pack a stored image (meta.json + layer/ tree) into a tar byte blob."""
    buf = io.BytesIO()
    meta = json.dumps(
        {"name": img.name, "version": img.version, "parents": list(img.parents)},
    ).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
        tar.add(img.layer, arcname="layer")
    return buf.getvalue()


def unpack_image(blob: bytes, dest: ImageStore, *, sudo: bool = False) -> str:
    """Unpack a tar blob into dest, save it, and return the stored `name:version` ref."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r") as tar:
            tar.extractall(tmp, filter="data")
        meta = json.loads((tmp / "meta.json").read_text(encoding="utf-8"))
        img = dest.save(
            meta["name"], meta["version"], tmp / "layer", tuple(meta["parents"]), sudo=sudo,
        )
    return f"{img.name}:{img.version}"


def pack_task(task_dir: Path) -> bytes:
    """Pack a task's artifacts dir (bundle/, hp/, task-meta.json) into a tar byte blob."""
    src = Path(task_dir)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for child in sorted(src.iterdir()):
            tar.add(child, arcname=child.name)
    return buf.getvalue()


def unpack_task(blob: bytes, dest_task_dir: Path) -> None:
    """Extract a task blob into dest_task_dir (creating it); mirrors `pack_task`."""
    dest = Path(dest_task_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r") as tar:
        tar.extractall(dest, filter="data")
