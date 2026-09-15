"""Blob (tar) pack/unpack for HTTP transfer: images (meta + layer/) and tasks (bundle/hp/meta)."""
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage


def _layer_has_unreadable(layer: Path) -> bool:
    """Return True if any file under `layer` is unreadable by the current user (root-owned 0640, …)."""
    try:
        for p in Path(layer).rglob("*"):
            if p.is_file() and not p.is_symlink():
                try:
                    with p.open("rb"):
                        pass
                except (PermissionError, OSError):
                    return True
    except (PermissionError, OSError):
        return True
    return False


def pack_image(img: StoredImage) -> bytes:
    """
    Pack a stored image (meta.json + layer/ tree) into a tar byte blob.

    Some image layers hold root-owned files with restrictive modes (`apt` locks,
    `/etc/shadow`, `/root/…`); pure-Python `tarfile` opens each file itself and
    trips on those.  When the layer isn't fully readable as the current user, we
    delegate the tar build to `sudo tar`, then read it back.
    """
    meta = json.dumps(
        {"name": img.name, "version": img.version, "parents": list(img.parents)},
    ).encode("utf-8")
    if _layer_has_unreadable(img.layer):
        return _pack_via_sudo_tar(img.layer, meta)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
        tar.add(img.layer, arcname="layer")
    return buf.getvalue()


def _pack_via_sudo_tar(layer: Path, meta: bytes) -> bytes:
    """
    Build the image blob using `sudo tar` when the layer holds root-only files.

    sudo/NOPASSWD only grants `tar`, not `chown` — so we avoid creating a root-owned
    output file entirely by writing meta.json to a user-owned staging dir and
    streaming the tar to stdout, which sudo hands back to the calling process.
    """
    with tempfile.TemporaryDirectory() as td:
        staging = Path(td)
        (staging / "meta.json").write_bytes(meta)
        # Tell tar to include meta.json (from staging) and layer/ (from the store, renamed).
        # `--transform` rewrites the on-disk path prefix so the archive holds `layer/...`.
        proc = subprocess.run(
            ["sudo", "tar", "-cf", "-",
             "-C", str(staging), "meta.json",
             "--transform", f"s|^{str(layer).lstrip('/')}|layer|",
             "-C", "/", str(layer).lstrip("/")],
            check=True, capture_output=True,
        )
        return proc.stdout


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
