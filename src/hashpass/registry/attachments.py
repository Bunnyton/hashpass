"""
Per-image attachment store on the pool: a free-text description plus arbitrary files.

Teacher-only (the auth gate lives in the server): a task's Taskfile carries reference
solutions, so this is never exposed to students. Keyed by image ref `name:version`;
data lives under `<root>/<name>/<version>/` with files in a `files/` subdir and a
sibling `meta.json` ({description, files:{name:{size, taskfile, uploaded_at}}}).
"""
import json
import re
import time
from pathlib import Path

_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")          # one ref path segment
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,()_-]{0,127}")  # an attachment file name


def _check(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.fullmatch(value):
        msg = f"недопустимое имя ({what}): {value!r}"
        raise ValueError(msg)
    return value


def safe_filename(filename: str) -> str:
    """Reduce an uploaded name to a safe basename, or raise ValueError."""
    base = Path(filename.strip().replace("\\", "/")).name
    return _check(_FILENAME, base, "файл")


class AttachmentStore:
    """A per-ref store of a description and named file blobs, persisted under `root`."""

    def __init__(self, root: Path) -> None:
        """Open (creating on write) the attachment store rooted at `root`."""
        self._root = Path(root)

    def _dir(self, ref: str) -> Path:
        name, _, version = ref.partition(":")
        version = _check(_COMPONENT, version or "latest", "версия")
        parts = [_check(_COMPONENT, seg, "образ") for seg in name.split("/") if seg]
        if not parts:
            msg = f"пустой ref: {ref!r}"
            raise ValueError(msg)
        return self._root.joinpath(*parts, version)

    def _meta_path(self, ref: str) -> Path:
        return self._dir(ref) / "meta.json"

    def _load(self, ref: str) -> dict[str, object]:
        path = self._meta_path(ref)
        if not path.exists():
            return {"description": "", "files": {}}
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("description", "")
        data.setdefault("files", {})
        return data

    def _save(self, ref: str, data: dict[str, object]) -> None:
        self._dir(ref).mkdir(parents=True, exist_ok=True)
        self._meta_path(ref).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                        encoding="utf-8")

    def set_description(self, ref: str, text: str) -> None:
        """Replace the image's description text."""
        data = self._load(ref)
        data["description"] = text
        self._save(ref, data)

    def put_file(self, ref: str, filename: str, blob: bytes, *, taskfile: bool = False) -> str:
        """Store (or replace) a file blob; return the safe name it was stored under."""
        name = safe_filename(filename)
        files_dir = self._dir(ref) / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        (files_dir / name).write_bytes(blob)
        data = self._load(ref)
        files = data["files"]
        if not isinstance(files, dict):
            files = {}
        files[name] = {"size": len(blob), "taskfile": taskfile, "uploaded_at": time.time()}
        data["files"] = files
        self._save(ref, data)
        return name

    def read_file(self, ref: str, filename: str) -> bytes:
        """Return a stored file's bytes (raises FileNotFoundError if absent)."""
        return (self._dir(ref) / "files" / safe_filename(filename)).read_bytes()

    def delete_file(self, ref: str, filename: str) -> bool:
        """Remove a stored file; return whether it existed."""
        name = safe_filename(filename)
        path = self._dir(ref) / "files" / name
        existed = path.exists()
        path.unlink(missing_ok=True)
        data = self._load(ref)
        files = data["files"] if isinstance(data.get("files"), dict) else {}
        if name in files:
            del files[name]
            data["files"] = files
            self._save(ref, data)
        return existed

    def describe(self, ref: str) -> dict[str, object]:
        """Return {description, files:[{name, size, taskfile, uploaded_at}]} sorted by name."""
        data = self._load(ref)
        files = data["files"] if isinstance(data.get("files"), dict) else {}
        rows = [{"name": n, **v} for n, v in sorted(files.items())]
        return {"description": str(data.get("description", "")), "files": rows}
