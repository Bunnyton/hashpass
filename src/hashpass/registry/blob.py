"""Image blob (tar) pack/unpack for HTTP transfer: a meta.json member + the layer/ tree."""
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
