"""Content digest of a task's grading artifacts (bundle + hidden /hp layer + meta)."""
# A basic integrity check: the pool stores this digest for a published task and refuses to grant
# credit for a submission whose locally-recomputed digest differs -- a student who edits the task
# to weaken its checks cannot get a signed pass. Not tamper-proof against local root; it stops
# casual tampering (see the spec's honesty note).
import hashlib
from pathlib import Path


def task_digest(task_dir: Path) -> str:
    """Return a deterministic sha256 (hex) over the task tree: each file's relative path + bytes."""
    root = Path(task_dir)
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        if path.is_file():
            h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()
