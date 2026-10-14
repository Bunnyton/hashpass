"""
The approved version of a task, kept while an update waits for approval (spec 2026-10-14).

The pool holds one generation per ref; when a push is about to overwrite the version students
are allowed to see, the server first copies it here -- the image blob, the `task/` dir and the
blob's digest -- and serves students from this copy until the admin approves the update.
A copy is replaced atomically (built next to the old one, then swapped in).
"""
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage
from hashpass.registry.attachments import ref_dir
from hashpass.registry.blob import pack_image

_BLOB = "layer.blob"
_TASK = "task"
_META = "meta.json"


class ApprovedStore:
    """Per-ref copies of the approved version under `root`."""

    def __init__(self, root: Path) -> None:
        """Open (creating on write) the store of approved copies at `root`."""
        self._root = Path(root)

    def _dir(self, ref: str) -> Path:
        return ref_dir(self._root, ref)

    def take(self, ref: str, img: StoredImage, task_dir: Path, store: ImageStore, *,
             task_digest: str = "") -> str:
        """Copy the current version (blob + task/) as the approved one; return its blob digest."""
        final = self._dir(ref)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.parent / f".{final.name}.{uuid.uuid4().hex}.new"
        old = final.parent / f".{final.name}.{uuid.uuid4().hex}.old"
        try:
            tmp.mkdir()
            src = store.blob_path_of(img) if img.blob else None
            if src is not None and src.exists():
                shutil.copyfile(src, tmp / _BLOB)
                digest = img.digest or hashlib.sha256((tmp / _BLOB).read_bytes()).hexdigest()
            else:                                     # a legacy record (layer/ only): pack it
                data = pack_image(img)
                (tmp / _BLOB).write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
            if task_dir.is_dir():
                shutil.copytree(task_dir, tmp / _TASK, symlinks=True)
            (tmp / _META).write_text(json.dumps({"digest": digest, "parents": list(img.parents),
                                                 "task_digest": task_digest}), encoding="utf-8")
            if final.exists():
                final.rename(old)
            tmp.rename(final)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)
        return digest

    def digest(self, ref: str) -> str | None:
        """Return the approved copy's blob digest, or None if there is no copy."""
        try:
            return str(json.loads((self._dir(ref) / _META).read_text(encoding="utf-8"))["digest"])
        except (OSError, ValueError, KeyError):
            return None

    def task_digest(self, ref: str) -> str | None:
        """Return the task digest the copy was taken at (the catalog's `approved_digest`), or None."""
        try:
            return str(json.loads((self._dir(ref) / _META).read_text(encoding="utf-8"))["task_digest"])
        except (OSError, ValueError, KeyError):
            return None

    def parents(self, ref: str) -> tuple[str, ...]:
        """Return the copy's image parents (its `from` chain), () if unknown."""
        try:
            return tuple(json.loads((self._dir(ref) / _META).read_text(encoding="utf-8"))["parents"])
        except (OSError, ValueError, KeyError):
            return ()

    def blob(self, ref: str) -> Path | None:
        """Return the approved copy's image blob, or None."""
        p = self._dir(ref) / _BLOB
        return p if p.is_file() else None

    def task_dir(self, ref: str) -> Path | None:
        """Return the approved copy's `task/` dir, or None."""
        p = self._dir(ref) / _TASK
        return p if p.is_dir() else None

    def remove(self, ref: str) -> None:
        """Drop the approved copy (the update was approved, or the task deleted)."""
        shutil.rmtree(self._dir(ref), ignore_errors=True)
