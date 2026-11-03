"""
A task's wiki on the pool: its own versions, on the side of the image and the task revisions.

User, 2026-11-03: «редактирование и версионирование wiki сделать немного отдельно — сбоку. То есть,
версии есть и есть их разница, но отдельно от остального образа, тогда не будет конфликтов —
можно будет запушить только из свежей версии, скачать изменения и править».

One wiki per repository, under `<repos>/<ns>/<name>/wiki/`: every version is a full snapshot
`v<N>/` (unchanged files are hard links to the previous version) and `versions.json` lists who,
when, why and which pages. A save names the version it started from (`base`); it passes unless a
page it touches was changed after `base` -- two authors on different pages never block each other.
"""
import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import tarfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from hashpass.registry.merges import tree_diff

MAIN = "wiki.md"                   # the main page, next to the Taskfile
FOLDER = "wiki"                    # every other page and picture
MAX_FILE = 8 * 1024 * 1024         # one picture (spec 2026-11-03)
MAX_TOTAL = 64 * 1024 * 1024       # a whole version
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
           ".webp": "image/webp"}
MARKDOWN = "text/markdown; charset=utf-8"


class WikiRejected(ValueError):  # noqa: N818  (reads as a verdict)
    """A path, a file type or a size the wiki does not take (the message is for people)."""


class WikiConflict(Exception):  # noqa: N818  (a state, not a failure)
    """The pages a save touches were changed on the pool after the version it started from."""

    def __init__(self, paths: list[str]) -> None:
        """Remember the conflicting pages."""
        super().__init__("wiki на пуле правили после твоей версии: " + ", ".join(paths))
        self.paths = paths


def check_path(path: str) -> str:
    """Return `path` if it is `wiki.md` or a page/picture under `wiki/`; else raise WikiRejected."""
    if path == MAIN:
        return path
    parts = path.split("/")
    ok = (len(parts) >= 2 and parts[0] == FOLDER  # noqa: PLR2004
          and all(_SEGMENT.fullmatch(p) for p in parts[1:])
          and Path(parts[-1]).suffix.lower() in {".md", *_IMAGES})
    if not ok:
        msg = (f"в wiki можно класть только {MAIN} и страницы .md или картинки (png, jpg, gif, webp) "
               f"в {FOLDER}/ — не {path!r}")
        raise WikiRejected(msg)
    return path


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def check_file(path: str, data: bytes) -> str:
    """Check one file (path, size, real type by its first bytes); return its Content-Type."""
    check_path(path)
    if len(data) > MAX_FILE:
        msg = f"{path}: файл больше {MAX_FILE // 1024 // 1024} МиБ"
        raise WikiRejected(msg)
    suffix = Path(path).suffix.lower()
    if suffix == ".md":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = f"{path}: страница не в UTF-8"
            raise WikiRejected(msg) from exc
        return MARKDOWN
    kind = _sniff(data)
    if kind != _IMAGES[suffix]:
        msg = f"{path}: это не картинка {suffix[1:].upper()} (SVG и другие файлы wiki не принимает)"
        raise WikiRejected(msg)
    return kind


def parse_tags(text: str) -> tuple[list[str], str]:
    """Split the `---` / `tags: a, b` / `---` block off the top of wiki.md: (tags, the rest)."""
    m = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", text, re.DOTALL)
    if not m:
        return [], text
    tags: list[str] = []
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "tags":
            for raw in value.strip().strip("[]").split(","):
                tag = raw.strip().strip("'\"").lstrip("#").strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
    return tags, text[m.end():]


def pack(files: dict[str, bytes]) -> bytes:
    """Pack wiki files (path -> bytes) into a tar.gz."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(files):
            info = tarfile.TarInfo(path)
            info.size = len(files[path])
            info.mtime = 0
            tar.addfile(info, io.BytesIO(files[path]))
    return buf.getvalue()


def unpack(blob: bytes) -> dict[str, bytes]:
    """Read a `pack` archive back, checking every member; a bad one raises WikiRejected."""
    out: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for member in tar:
                if member.isdir():
                    continue
                if not member.isfile():
                    msg = f"в архиве wiki не файл: {member.name!r}"
                    raise WikiRejected(msg)
                path = check_path(member.name.removeprefix("./"))
                total += member.size
                if member.size > MAX_FILE or total > MAX_TOTAL:
                    msg = "wiki больше допустимого размера"
                    raise WikiRejected(msg)
                fh = tar.extractfile(member)
                out[path] = fh.read() if fh else b""
    except (tarfile.TarError, EOFError, OSError) as exc:
        msg = f"архив wiki не читается: {exc}"
        raise WikiRejected(msg) from exc
    return out


class WikiStore:
    """The wiki of one repository: versions 1..N, 0 meaning «no wiki yet»."""

    def __init__(self, root: Path, name: str) -> None:
        """Open the wiki of repository `name` (`ns/repo`) under `root` (the pool's `.repos`)."""
        parts = name.split("/")
        if len(parts) != 2 or not all(_SEGMENT.fullmatch(p) for p in parts):  # noqa: PLR2004
            msg = f"недопустимое имя репозитория: {name!r}"
            raise ValueError(msg)
        self.name = name
        self._dir = Path(root).joinpath(*parts, FOLDER)

    # -- reading --------------------------------------------------------------

    def _index(self) -> list[dict]:
        try:
            rows = json.loads((self._dir / "versions.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return rows if isinstance(rows, list) else []

    def head(self) -> int:
        """Return the newest version number (0: there is no wiki)."""
        rows = self._index()
        return int(rows[-1]["n"]) if rows else 0

    def exists(self) -> bool:
        """Tell whether the repository has a wiki."""
        return self.head() > 0

    def versions(self) -> list[dict]:
        """Every version, newest first: {n, by, at, message, changed}."""
        return [dict(r) for r in reversed(self._index())]

    def snapshot(self, n: int | None = None) -> Path | None:
        """Return the folder of version `n` (None: the newest); None for version 0."""
        n = self.head() if n is None else n
        return self._dir / f"v{n}" if n > 0 else None

    def files(self, n: int | None = None) -> dict[str, bytes]:
        """Return version `n` (None: the newest) as {path: bytes}; {} for version 0."""
        root = self.snapshot(n)
        if root is None or not root.is_dir():
            return {}
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in sorted(root.rglob("*")) if p.is_file()}

    def read(self, path: str, n: int | None = None) -> bytes:
        """Read one file of version `n`; a missing one raises FileNotFoundError."""
        root = self.snapshot(n)
        target = root / check_path(path) if root else None
        if target is None or not target.is_file():
            raise FileNotFoundError(path)
        return target.read_bytes()

    def names(self, n: int | None = None) -> list[str]:
        """Return the paths of version `n` (None: the newest) without reading them."""
        root = self.snapshot(n)
        if root is None or not root.is_dir():
            return []
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())

    def _base(self, base: int) -> int:
        """Treat a version this wiki never had (the pool was reset, the wiki made anew) as «from nothing»."""
        return base if 0 <= base <= self.head() else 0

    def changed_since(self, base: int) -> set[str]:
        """Return the pages changed by the versions after `base`."""
        base = self._base(base)
        return {p for r in self._index() if int(r["n"]) > base for p in r.get("changed", [])}

    def _clash(self, base: int, changes: dict[str, bytes | None], head_files: dict[str, bytes]) -> list[str]:
        """Pages both sides changed since `base` -- and that really differ from the newest version."""
        return sorted(p for p in set(changes) & self.changed_since(base) if changes[p] != head_files.get(p))

    def local_changes(self, base: int, local: dict[str, bytes]) -> dict[str, bytes | None]:
        """Return what `local` changed against version `base` (None: deleted)."""
        old = self.files(self._base(base))
        out: dict[str, bytes | None] = {p: data for p, data in local.items() if old.get(p) != data}
        out.update({p: None for p in old if p not in local})
        return out

    def conflicts(self, base: int, local: dict[str, bytes]) -> list[str]:
        """Return the pages `local` and the pool both changed since `base`, now different."""
        return self._clash(base, self.local_changes(base, local), self.files())

    def rebase(self, base: int, local: dict[str, bytes], *, keep_mine: bool = False) -> tuple[int, dict[str, bytes]]:
        """
        Return (head, the newest wiki with `local`'s own changes on top); write nothing.

        A page both sides changed raises WikiConflict -- or, with `keep_mine`, stays as `local`
        has it (the caller puts the pool's copy aside for the author to reconcile).
        """
        mine = self.local_changes(base, local)
        head = self.head()
        merged = self.files(head)
        clash = self._clash(base, mine, merged)
        if clash and not keep_mine:
            raise WikiConflict(clash)
        for path, data in mine.items():
            if data is None:
                merged.pop(path, None)
            else:
                merged[path] = data
        return head, merged

    def diff(self, a: int, b: int) -> list[dict]:
        """Per-file differences from version `a` to version `b`."""
        return tree_diff(self.snapshot(a), self.snapshot(b))

    # -- writing --------------------------------------------------------------

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self._dir.mkdir(parents=True, exist_ok=True)
        with (self._dir / ".lock").open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def save(self, base: int, changes: dict[str, bytes | None], *, by: str, message: str = "") -> int:
        """
        Write `changes` (path -> bytes, None = delete) on top of the newest version.

        Return the new version, or the newest one when nothing really changes. A page changed
        after `base` raises WikiConflict; a bad path/type/size raises WikiRejected.
        """
        for path, data in changes.items():
            if data is None:
                check_path(path)
            else:
                check_file(path, data)
        with self._locked():
            head = self.head()
            current = self.files(head)
            clash = self._clash(base, changes, current)
            if clash:
                raise WikiConflict(clash)
            real = {p: d for p, d in changes.items() if current.get(p) != d and not (d is None and p not in current)}
            if not real:
                return head
            after = {**current, **{p: d for p, d in real.items() if d is not None}}
            for p, d in real.items():
                if d is None:
                    after.pop(p, None)
            if MAIN not in after and after:
                msg = f"у wiki должна остаться главная страница {MAIN}"
                raise WikiRejected(msg)
            if sum(len(d) for d in after.values()) > MAX_TOTAL:
                msg = f"wiki больше {MAX_TOTAL // 1024 // 1024} МиБ"
                raise WikiRejected(msg)
            n = head + 1
            self._write_snapshot(n, head, after, real)
            rows = [*self._index(), {"n": n, "by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                     "message": message[:500], "changed": sorted(real)}]
            tmp = self._dir / f".versions.{uuid.uuid4().hex}"
            tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._dir / "versions.json")
            return n

    def _write_snapshot(self, n: int, head: int, after: dict[str, bytes], real: dict[str, bytes | None]) -> None:
        old = self.snapshot(head)
        tmp = self._dir / f".v{n}.{uuid.uuid4().hex}"
        try:
            for path, data in after.items():
                target = tmp / path
                target.parent.mkdir(parents=True, exist_ok=True)
                if path not in real and old is not None and (old / path).is_file():
                    os.link(old / path, target)              # unchanged: no second copy
                else:
                    target.write_bytes(data)
            tmp.mkdir(parents=True, exist_ok=True)
            final = self._dir / f"v{n}"
            shutil.rmtree(final, ignore_errors=True)         # a half-written leftover of a crash
            tmp.rename(final)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def copy_to(self, other: "WikiStore") -> None:
        """Copy this wiki with its whole history into `other` (a fork); a wiki there stays."""
        if not self._dir.is_dir() or other.exists():
            return
        other._dir.parent.mkdir(parents=True, exist_ok=True)  # noqa: SLF001
        shutil.copytree(self._dir, other._dir, dirs_exist_ok=True,  # noqa: SLF001
                        ignore=shutil.ignore_patterns(".lock", ".v*", ".versions.*"))

    def drop(self) -> None:
        """Remove the wiki with its history (the repository is gone)."""
        shutil.rmtree(self._dir, ignore_errors=True)
