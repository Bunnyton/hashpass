"""Server-side per-student task progress (passed/failed), persisted as one JSON file per user."""
import json
from pathlib import Path


class ProgressStore:
    """user -> {task_ref -> {status, ts, global_key, digest}}, one JSON file per user."""

    def __init__(self, root: Path) -> None:
        """Open (creating on write) the progress dir (one <user>.json per student)."""
        self._root = Path(root)

    def _path(self, user: str) -> Path:
        return self._root / f"{user}.json"

    def get(self, user: str) -> dict[str, dict[str, object]]:
        """Return one user's task_ref -> record map ({} if none)."""
        path = self._path(user)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def record(self, user: str, task_ref: str, *, status: str,  # noqa: PLR0913
               ts: str, global_key: str | None = None, digest: str = "",
               history: list[dict[str, object]] | None = None,
               authenticity: dict[str, object] | None = None) -> None:
        """Record (overwrite) a user's result for one task, with optional history + anti-bot signal."""
        data = self.get(user)
        rec: dict[str, object] = {"status": status, "ts": ts, "global_key": global_key,
                                  "digest": digest}
        if history is not None:
            rec["history"] = history
        if authenticity is not None:
            rec["authenticity"] = authenticity
        data[task_ref] = rec
        self._root.mkdir(parents=True, exist_ok=True)
        self._path(user).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def delete(self, user: str) -> None:
        """Remove a user's progress file (no-op if absent)."""
        self._path(user).unlink(missing_ok=True)

    def all(self) -> dict[str, dict[str, dict[str, object]]]:
        """Return every user's progress map (for the teacher dashboard)."""
        result: dict[str, dict[str, dict[str, object]]] = {}
        if self._root.exists():
            for path in sorted(self._root.glob("*.json")):
                result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        return result
