"""
A task's sources on the pool, kept as FILES.

User, 2026-10-14: «давай не архивом, давай все-таки все файлы, но скачать можно архив».

`hashengine push` sends the task directory as one tar.gz; the pool unpacks it into
`<root>/<name>/<version>/` so authors and admins can browse it file by file (hashpass viewer, web
card), and packs it back into an archive on request (`hashengine source`). A new push replaces
the whole tree atomically: unpacked next to it first, then swapped in.
"""
import io
import shutil
import tarfile
import uuid
from pathlib import Path

from hashpass.registry.attachments import ref_dir


class SourceStore:
    """Per-ref source trees under `root`."""

    def __init__(self, root: Path) -> None:
        """Open (creating on write) the source store rooted at `root`."""
        self._root = Path(root)

    def _dir(self, ref: str) -> Path:
        return ref_dir(self._root, ref)

    def put_archive(self, ref: str, blob: bytes) -> None:
        """Replace `ref`'s tree with the archive's files; an escaping member raises TarError."""
        final = self._dir(ref)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.parent / f".{final.name}.{uuid.uuid4().hex}.new"
        old = final.parent / f".{final.name}.{uuid.uuid4().hex}.old"
        try:
            tmp.mkdir()
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
                tar.extractall(tmp, filter="data")
            if final.exists():
                final.rename(old)
            tmp.rename(final)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)

    def listing(self, ref: str) -> list[dict[str, object]]:
        """List every file and directory of the tree, sorted by path: {path, size, dir}."""
        base = self._dir(ref)
        if not base.is_dir():
            return []
        rows = []
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(base).as_posix()
            is_dir = p.is_dir() and not p.is_symlink()
            rows.append({"path": rel, "size": 0 if is_dir else p.lstat().st_size, "dir": is_dir})
        return rows

    def read(self, ref: str, path: str) -> bytes:
        """Read one file; a path leaving the tree raises ValueError, a missing one FileNotFoundError."""
        base = self._dir(ref).resolve()
        target = (base / path).resolve()
        if path.startswith("/") or not target.is_relative_to(base) or target == base:
            msg = f"путь вне исходников задания: {path!r}"
            raise ValueError(msg)
        if not target.is_file():
            raise FileNotFoundError(path)
        return target.read_bytes()

    def archive(self, ref: str) -> bytes:
        """Pack the tree back into a tar.gz (paths relative), as `hashengine source` unpacks it."""
        base = self._dir(ref)
        if not base.is_dir():
            raise FileNotFoundError(ref)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for p in sorted(base.rglob("*")):
                tar.add(p, arcname=p.relative_to(base).as_posix(), recursive=False)
        return buf.getvalue()

    def remove(self, ref: str) -> None:
        """Forget `ref`'s sources (task deleted)."""
        shutil.rmtree(self._dir(ref), ignore_errors=True)
