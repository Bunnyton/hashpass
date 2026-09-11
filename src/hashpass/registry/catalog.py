"""
Task catalog grouped into teacher-managed blocks, persisted as JSON.

A task's display name IS its image ref (no separate title). Order is implicit in the JSON
arrays (blocks, and tasks within a block); the student-facing number is derived from that
order. Availability is per block: a task is open to students iff its block is open.
"""
import json
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CatalogEntry:
    """One task in the curriculum; its display name is the image ref `name:version`."""

    number: int          # 1-based position across the whole ordered catalog (derived)
    name: str
    version: str
    digest: str
    block_id: str
    block_name: str
    available: bool      # visible to students: block.open AND NOT task.hidden
    hidden: bool = False  # per-task teacher override (default: visible when the block is open)

    @property
    def ref(self) -> str:
        """The image/task ref `name:version`."""
        return f"{self.name}:{self.version}"

    def as_dict(self) -> dict[str, object]:
        """Serializable view (used by /catalog, the student menu, and the web)."""
        return {"number": self.number, "name": self.name, "version": self.version,
                "digest": self.digest, "ref": self.ref, "block_id": self.block_id,
                "block_name": self.block_name, "available": self.available,
                "hidden": self.hidden}


@dataclass(frozen=True)
class Block:
    """A named, ordered group of tasks that a teacher opens or closes as a unit."""

    id: str
    name: str
    open: bool
    entries: list[CatalogEntry]

    def as_dict(self) -> dict[str, object]:
        """Serializable view including the block's ordered tasks."""
        return {"id": self.id, "name": self.name, "open": self.open,
                "tasks": [e.as_dict() for e in self.entries]}


def _new_id() -> str:
    return secrets.token_hex(4)


def _migrate(old: dict[str, object]) -> dict[str, object]:
    """Lift the legacy flat {number: {name,version,title,digest,available}} map into one block."""
    tasks = []
    for _n, d in sorted(old.items(), key=lambda kv: int(kv[0])):
        if isinstance(d, dict):
            tasks.append({"name": str(d.get("name", "")), "version": str(d.get("version", "")),
                          "digest": str(d.get("digest", ""))})
    return {"blocks": [{"id": _new_id(), "name": "Задания", "open": True, "tasks": tasks}]}


class Catalog:
    """Blocks of tasks, persisted as JSON. Numbers/availability are derived from block order+state."""

    def __init__(self, path: Path) -> None:
        """Open (creating on write) the catalog at path."""
        self._path = Path(path)

    def _load(self) -> dict[str, object]:
        if not self._path.exists():
            return {"blocks": []}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"blocks": []}
        if "blocks" not in data:              # legacy flat catalog -> one block
            return _migrate(data)
        return data

    def _save(self, data: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def blocks(self) -> list[Block]:
        """Return blocks in order, each carrying its ordered CatalogEntry list (numbers derived)."""
        result: list[Block] = []
        number = 0
        for b in self._load().get("blocks", []):
            if not isinstance(b, dict):
                continue
            is_open = bool(b.get("open", True))
            entries: list[CatalogEntry] = []
            for t in b.get("tasks", []):
                number += 1
                hidden = bool(t.get("hidden", False))
                entries.append(CatalogEntry(
                    number, str(t.get("name", "")), str(t.get("version", "")),
                    str(t.get("digest", "")), str(b.get("id", "")), str(b.get("name", "")),
                    available=is_open and not hidden, hidden=hidden))
            result.append(Block(str(b.get("id", "")), str(b.get("name", "")), is_open, entries))
        return result

    def entries(self) -> list[CatalogEntry]:
        """Return every task, flattened in catalog order (available and closed alike)."""
        return [e for block in self.blocks() for e in block.entries]

    def find(self, ref: str) -> CatalogEntry | None:
        """Return the task whose ref matches `name:version`, or None."""
        return next((e for e in self.entries() if e.ref == ref), None)

    # -- mutations -------------------------------------------------------------

    def add_block(self, name: str) -> str:
        """Create a new (open) block; return its id."""
        data = self._load()
        block_id = _new_id()
        data.setdefault("blocks", []).append({"id": block_id, "name": name, "open": True, "tasks": []})
        self._save(data)
        return block_id

    def rename_block(self, block_id: str, name: str) -> bool:
        """Rename a block; return whether it existed."""
        data = self._load()
        for b in data.get("blocks", []):
            if b.get("id") == block_id:
                b["name"] = name
                self._save(data)
                return True
        return False

    def remove_block(self, block_id: str) -> bool:
        """Remove an EMPTY block; return whether one was removed (non-empty blocks are kept)."""
        data = self._load()
        blocks = data.get("blocks", [])
        keep = [b for b in blocks if not (b.get("id") == block_id and not b.get("tasks"))]
        if len(keep) == len(blocks):
            return False
        data["blocks"] = keep
        self._save(data)
        return True

    def set_block_open(self, block_id: str, *, open_: bool) -> bool:
        """Open or close a whole block; return whether it existed."""
        data = self._load()
        for b in data.get("blocks", []):
            if b.get("id") == block_id:
                b["open"] = open_
                self._save(data)
                return True
        return False

    def add_task(self, ref: str, digest: str, *, block_id: str | None = None) -> None:
        """Append a task (auto-numbered by position) to a block (default: the last/created block)."""
        name, _, version = ref.partition(":")
        data = self._load()
        blocks = data.setdefault("blocks", [])
        if not blocks:
            blocks.append({"id": _new_id(), "name": "Задания", "open": True, "tasks": []})
        target = next((b for b in blocks if b.get("id") == block_id), None) or blocks[-1]
        target.setdefault("tasks", [])
        target["tasks"] = [t for t in target["tasks"] if f"{t.get('name')}:{t.get('version')}" != ref]
        for b in blocks:   # a ref lives in exactly one block
            b["tasks"] = [t for t in b.get("tasks", [])
                          if f"{t.get('name')}:{t.get('version')}" != ref]
        target["tasks"].append({"name": name, "version": version, "digest": digest})
        self._save(data)

    def set_task_hidden(self, ref: str, *, hidden: bool) -> bool:
        """Toggle a single task's per-teacher hidden flag; return whether it existed."""
        data = self._load()
        for b in data.get("blocks", []):
            for t in b.get("tasks", []):
                if f"{t.get('name')}:{t.get('version')}" == ref:
                    t["hidden"] = hidden
                    self._save(data)
                    return True
        return False

    def remove_task(self, ref: str) -> bool:
        """Remove a task from whatever block holds it; return whether one was removed."""
        data = self._load()
        removed = False
        for b in data.get("blocks", []):
            before = len(b.get("tasks", []))
            b["tasks"] = [t for t in b.get("tasks", [])
                          if f"{t.get('name')}:{t.get('version')}" != ref]
            removed = removed or len(b["tasks"]) != before
        if removed:
            self._save(data)
        return removed

    def set_layout(self, layout: list[dict[str, object]]) -> None:
        """
        Rebuild the whole catalog from a drag-and-drop layout, preserving digests by ref.

        `layout` is an ordered list of blocks: {id?, name, open, tasks: [ref, ...]}. Unknown refs
        (no stored digest) are dropped. This is how reorder / move-between-blocks is applied.
        """
        digest = {e.ref: e.digest for e in self.entries()}
        hidden = {e.ref: e.hidden for e in self.entries()}
        prev = {str(b.get("id")): b for b in self._load().get("blocks", []) if isinstance(b, dict)}
        blocks: list[dict[str, object]] = []
        for b in layout:
            block_id = str(b.get("id") or _new_id())
            was = prev.get(block_id, {})
            tasks = []
            for raw in b.get("tasks", []):
                ref = str(raw)
                if ref not in digest:
                    continue
                name, _, version = ref.partition(":")
                tasks.append({"name": name, "version": version, "digest": digest[ref],
                              "hidden": hidden.get(ref, False)})
            blocks.append({"id": block_id, "name": str(b.get("name", was.get("name", ""))),
                           "open": bool(b.get("open", was.get("open", True))), "tasks": tasks})
        self._save({"blocks": blocks})
