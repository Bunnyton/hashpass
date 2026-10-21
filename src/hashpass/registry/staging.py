"""
A push in progress: everything one revision will hold, gathered before `commit` (spec §2.3).

A staging area lives inside the pool's store root (`.staging/<id>/`, the same filesystem, so
commit moves directories with a rename): an ImageStore for the blob (+ `task/` next to it), an
AttachmentStore and a SourceStore, all keyed by `name:tag` like the real ones, and `intent.json`
(who opened it, for which tag, publish flags). Areas older than a day are swept.
"""
import json
import secrets
import shutil
import time
from pathlib import Path

from hashpass.imagestore.store import ImageStore
from hashpass.registry.attachments import AttachmentStore
from hashpass.registry.sources import SourceStore

STAGING_DIR = ".staging"
_ID_LEN = 16                       # bytes -> 32 hex chars
_MAX_AGE = 24 * 60 * 60


class Staging:
    """One open staging area."""

    def __init__(self, root: Path, sid: str) -> None:
        """Open the area `sid` under the pool root `root` (it may not exist yet)."""
        if not sid or not all(c in "0123456789abcdef" for c in sid):
            msg = "bad staging id"
            raise ValueError(msg)
        self.sid = sid
        self.dir = Path(root) / STAGING_DIR / sid
        self.images = ImageStore(self.dir / "images")
        self.attachments = AttachmentStore(self.dir / "attachments")
        self.sources = SourceStore(self.dir / "sources")

    @property
    def intent(self) -> dict:
        try:
            return json.loads((self.dir / "intent.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_intent(self, intent: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "intent.json").write_text(json.dumps(intent, ensure_ascii=False), encoding="utf-8")

    def exists(self) -> bool:
        return (self.dir / "intent.json").is_file()

    def remove(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def new_staging(root: Path, *, owner: str, name: str, tag: str) -> Staging:
    """Open a fresh area for one push of `name:tag` by `owner`."""
    st = Staging(root, secrets.token_hex(_ID_LEN))
    st.save_intent({"owner": owner, "name": name, "tag": tag, "publish": False, "block": "",
                    "created": time.time()})
    return st


def sweep_stale(root: Path, max_age: float = _MAX_AGE) -> None:
    """Remove areas older than `max_age` seconds (a push that never committed)."""
    base = Path(root) / STAGING_DIR
    if not base.is_dir():
        return
    now = time.time()
    for d in base.iterdir():
        try:
            created = float(json.loads((d / "intent.json").read_text(encoding="utf-8"))["created"])
        except (OSError, ValueError, KeyError, TypeError):
            created = d.stat().st_mtime
        if now - created > max_age:
            shutil.rmtree(d, ignore_errors=True)
