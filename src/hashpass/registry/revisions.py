"""
A repository's tags and their immutable, numbered revisions (spec 2026-10-21 §2).

Every push into a tag adds revision `tag_vN`; nothing is overwritten and numbers are never reused
(`next` survives a removal). `tag` alone and `tag_latest` mean the newest revision. The index of a
repository `owner/name` lives in `<root>/<owner>/<name>/repo.json`; writers hold an exclusive
`flock` on `.lock` next to it, so two pushes racing for the same tag get distinct numbers.
"""
import contextlib
import fcntl
import json
import os
import re
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REVISION_RE = re.compile(r"^(?P<tag>.+)_v(?P<n>[1-9][0-9]*)$")
_LATEST = "_latest"
_RESERVED = re.compile(r"(_v[0-9]+|_latest)$")
VISIBILITIES = ("public", "private")


def check_tag(tag: str) -> None:
    """Refuse a tag ending in a system suffix (`_vN`, `_latest`): those name revisions, not tags."""
    if _RESERVED.search(tag):
        msg = (f"тег «{tag}» оканчивается на зарезервированный суффикс (_vN или _latest) — "
               "так система называет ревизии; выберите другой тег")
        raise ValueError(msg)


def revision_version(tag: str, n: int) -> str:
    """Return the stored version of revision `n` of `tag`: ("1", 3) -> "1_v3"."""
    return f"{tag}_v{n}"


def parse_version(version: str) -> tuple[str, int | None, bool]:
    """Split a requested version into (tag, revision number or None, explicitly `_latest`)."""
    if version.endswith(_LATEST) and len(version) > len(_LATEST):
        return version[: -len(_LATEST)], None, True
    m = REVISION_RE.match(version)
    if m:
        return m.group("tag"), int(m.group("n")), False
    return version, None, False


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class Revision:
    """One immutable revision of a tag: what it holds (digests), what it stands on, who made it."""

    n: int
    image_digest: str
    task_digest: str
    parents: tuple[str, ...]
    at: str
    by: str
    merged_from: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"n": self.n, "image_digest": self.image_digest, "task_digest": self.task_digest,
                "parents": list(self.parents), "at": self.at, "by": self.by,
                "merged_from": self.merged_from}


def _revision(raw: dict) -> Revision:
    return Revision(int(raw["n"]), str(raw.get("image_digest", "")), str(raw.get("task_digest", "")),
                    tuple(str(p) for p in raw.get("parents", [])), str(raw.get("at", "")),
                    str(raw.get("by", "")), str(raw.get("merged_from", "")))


class RepoIndex:
    """The tags + revisions + repository settings of one `owner/name`."""

    def __init__(self, root: Path, name: str) -> None:
        """Open the index of `name` under `root` (nothing is created until a locked write)."""
        self._dir = Path(root) / name
        self._path = self._dir / "repo.json"
        self._writable = False
        self._data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        data.setdefault("visibility", "public")
        data.setdefault("hide_sources", False)
        data.setdefault("fork_of", "")
        data.setdefault("tags", {})
        return data

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".repo-", suffix=".tmp", dir=self._dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            Path(tmp).replace(self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                Path(tmp).unlink()
            raise

    @contextlib.contextmanager
    def locked(self) -> Iterator["RepoIndex"]:
        """Hold the repository's write lock; re-read the index inside it; writes save at once."""
        self._dir.mkdir(parents=True, exist_ok=True)
        with (self._dir / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self._data = self._load()
                self._writable = True
                yield self
            finally:
                self._writable = False
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _need_lock(self) -> None:
        if not self._writable:
            msg = "RepoIndex: writes happen only inside locked()"
            raise RuntimeError(msg)

    @property
    def exists(self) -> bool:
        return self._path.exists()

    @property
    def visibility(self) -> str:
        return str(self._data["visibility"])

    @property
    def hide_sources(self) -> bool:
        return bool(self._data["hide_sources"])

    @property
    def fork_of(self) -> str:
        return str(self._data["fork_of"])

    def set_meta(self, **fields: object) -> None:
        """Change repository settings: visibility, hide_sources, fork_of."""
        self._need_lock()
        if "visibility" in fields and fields["visibility"] not in VISIBILITIES:
            msg = f"видимость — {' или '.join(VISIBILITIES)}"
            raise ValueError(msg)
        for key in ("visibility", "hide_sources", "fork_of"):
            if key in fields:
                self._data[key] = fields[key]
        self._save()

    def tags(self) -> list[str]:
        return sorted(t for t, v in self._data["tags"].items() if v.get("revisions"))

    def revisions(self, tag: str) -> list[Revision]:
        raw = self._data["tags"].get(tag, {}).get("revisions", [])
        return sorted((_revision(r) for r in raw), key=lambda r: r.n)

    def latest(self, tag: str) -> Revision | None:
        revs = self.revisions(tag)
        return revs[-1] if revs else None

    def get(self, tag: str, n: int) -> Revision | None:
        return next((r for r in self.revisions(tag) if r.n == n), None)

    def add(self, tag: str, fields: dict) -> Revision:
        """Append the next revision of `tag` (number = the tag's counter, never reused)."""
        self._need_lock()
        entry = self._data["tags"].setdefault(tag, {"next": 1, "revisions": []})
        n = int(entry.get("next", 1))
        rev = _revision({**fields, "n": n, "at": fields.get("at") or _now()})
        entry["revisions"].append(rev.as_dict())
        entry["next"] = n + 1
        self._save()
        return rev

    def remove(self, tag: str, n: int) -> None:
        """Drop revision `n` of `tag` from the index (its number stays used)."""
        self._need_lock()
        entry = self._data["tags"].get(tag)
        if entry is None:
            return
        entry["revisions"] = [r for r in entry["revisions"] if int(r["n"]) != n]
        self._save()

    def as_dict(self) -> dict[str, object]:
        """Return the public view: settings + every tag's revisions (oldest first)."""
        return {"visibility": self.visibility, "hide_sources": self.hide_sources,
                "fork_of": self.fork_of,
                "tags": {t: [r.as_dict() for r in self.revisions(t)] for t in self.tags()}}
