"""
Pool-wide settings an admin switches (spec 2026-10-14): for now, auto-approval of every task.

Off by default: every new or updated task waits for an admin's approval unless this switch or
the author's own flag (`UserStore.auto_approve`) is on.
"""
import json
from pathlib import Path


class PoolSettings:
    """`pool-settings.json` next to the catalog."""

    def __init__(self, path: Path) -> None:
        """Open (creating on write) the settings file at `path`."""
        self._path = Path(path)

    def _load(self) -> dict[str, object]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def auto_approve(self) -> bool:
        """Whether every task on this pool approves itself on push."""
        return bool(self._load().get("auto_approve", False))

    def set_auto_approve(self, *, on: bool) -> None:
        """Switch pool-wide auto-approval."""
        data = self._load()
        data["auto_approve"] = on
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
