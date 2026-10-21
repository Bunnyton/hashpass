"""
Merge requests: a fork's revision offered back to the repository it came from (spec §2.8).

Stored next to the target repository's index (`.repos/<owner>/<name>/merges.json`). One open
request per (fork tag -> target tag); a newer offer from the same fork tag refreshes it.
"""
import difflib
import json
import time
import uuid
from pathlib import Path

_MAX_DIFF_FILE = 256 * 1024
STATES = ("open", "merged", "rejected", "withdrawn")


class MergeRequests:
    """The merge requests into one repository."""

    def __init__(self, repo_dir: Path) -> None:
        """Open the list kept in `repo_dir/merges.json`."""
        self._path = Path(repo_dir) / "merges.json"

    def all(self) -> list[dict]:
        try:
            return list(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _save(self, rows: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, mid: str) -> dict | None:
        return next((r for r in self.all() if r["id"] == mid), None)

    def offer(self, *, src: str, to_tag: str, by: str, comment: str) -> dict:
        """Open (or refresh) the request from `src` (a fork revision) into `to_tag`."""
        rows = self.all()
        src_tag = src.rpartition("_v")[0]
        row = next((r for r in rows if r["state"] == "open" and r["to_tag"] == to_tag
                    and r["from"].rpartition("_v")[0] == src_tag), None)
        if row is None:
            row = {"id": f"m-{uuid.uuid4().hex[:8]}", "to_tag": to_tag, "state": "open",
                   "reason": "", "decided_by": "", "decided_at": 0.0, "result": ""}
            rows.append(row)
        row.update({"from": src, "by": by, "comment": comment[:2000], "at": time.time()})
        self._save(rows)
        return row

    def close(self, mid: str, state: str, *, by: str, reason: str = "", result: str = "") -> dict | None:
        rows = self.all()
        row = next((r for r in rows if r["id"] == mid and r["state"] == "open"), None)
        if row is None:
            return None
        row.update({"state": state, "decided_by": by, "decided_at": time.time(),
                    "reason": reason[:500], "result": result})
        self._save(rows)
        return row


def tree_diff(old: Path | None, new: Path | None) -> list[dict]:
    """Per-file differences between two source trees: added / removed / changed (+ unified diff)."""
    def files(root: Path | None) -> dict[str, Path]:
        if root is None or not root.is_dir():
            return {}
        return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}

    a, b = files(old), files(new)
    out: list[dict] = []
    for path in sorted(set(a) | set(b)):
        if path not in a:
            out.append({"path": path, "change": "added", "diff": _text_diff(None, b[path], path)})
        elif path not in b:
            out.append({"path": path, "change": "removed", "diff": _text_diff(a[path], None, path)})
        elif a[path].read_bytes() != b[path].read_bytes():
            out.append({"path": path, "change": "changed", "diff": _text_diff(a[path], b[path], path)})
    return out


def _text_diff(old: Path | None, new: Path | None, path: str) -> str:
    def lines(p: Path | None) -> list[str] | None:
        if p is None:
            return []
        data = p.read_bytes()
        if len(data) > _MAX_DIFF_FILE:
            return None
        try:
            return data.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            return None

    a, b = lines(old), lines(new)
    if a is None or b is None:
        return "(двоичный или слишком большой файл)"
    return "".join(difflib.unified_diff(a, b, fromfile=f"a/{path}", tofile=f"b/{path}"))
