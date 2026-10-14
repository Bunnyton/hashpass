"""
Task catalog grouped into teacher-managed blocks, persisted as JSON.

A task's display name IS its image ref (no separate title). Order is implicit in the JSON
arrays (blocks, and tasks within a block); the student-facing number is derived from that
order. Availability is per block: a task is open to students iff its block is open.

Moderation (spec 2026-10-14): a task is `pending` until an admin approves it (or auto-approval is
on), `approved` -- and then `approved_digest` names the version students get -- or `rejected`
(kept a week, then purged). A new push of an approved task waits for approval again while
students keep the approved version. A catalog written before moderation reads as approved.
"""
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REJECT_TTL = 7 * 24 * 3600   # a rejected task lives a week, then the pool deletes it
_STATES = ("pending", "approved", "rejected")


@dataclass(frozen=True)
class CatalogEntry:
    """One task in the curriculum; its display name is the image ref `name:version`."""

    number: int          # 1-based position across the whole ordered catalog (derived)
    name: str
    version: str
    digest: str
    block_id: str
    block_name: str
    available: bool      # visible to students: approved version AND block.open AND NOT hidden
    hidden: bool = False  # per-task teacher override (default: visible when the block is open)
    block_open: bool = True  # the block's own state (staff toggle it: web ⋯ menu, hashpass `o`)
    state: str = "approved"       # pending | approved | rejected
    approved_digest: str = ""     # the version students get ("" = never approved)
    reason: str = ""              # why it was rejected (optional)
    rejected_at: float = 0.0      # when (unix), for the weekly purge
    approved_image: str = ""      # blob digest of the approved image ("" = legacy: the current one)

    @property
    def owner(self) -> str:
        """The author: the ref's namespace (`bob/lab` -> bob); "" for a ref without one (admin)."""
        return self.name.split("/", 1)[0] if "/" in self.name else ""

    @property
    def ref(self) -> str:
        """The image/task ref `name:version`."""
        return f"{self.name}:{self.version}"

    def as_dict(self) -> dict[str, object]:
        """Serializable view (used by /catalog, the student menu, and the web)."""
        return {"number": self.number, "name": self.name, "version": self.version,
                "digest": self.digest, "ref": self.ref, "block_id": self.block_id,
                "block_name": self.block_name, "available": self.available,
                "hidden": self.hidden, "block_open": self.block_open,
                "state": self.state, "approved_digest": self.approved_digest,
                "reason": self.reason, "rejected_at": self.rejected_at,
                "expires_at": self.rejected_at + REJECT_TTL if self.state == "rejected" else None,
                "pending_update": self.state != "approved" and bool(self.approved_digest),
                "owner": self.owner}


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


def _moderation(t: dict) -> tuple[str, str, str, float]:
    """(state, approved_digest, reason, rejected_at) of a stored task; a pre-moderation one is approved."""
    if "state" not in t:
        return "approved", str(t.get("digest", "")), "", 0.0
    state = str(t.get("state")) if t.get("state") in _STATES else "pending"
    return (state, str(t.get("approved_digest") or ""), str(t.get("reason") or ""),
            float(t.get("rejected_at") or 0.0))


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


def _target_block(blocks: list[dict], block_id: str | None, block_name: str | None) -> dict:
    """Return the block to publish into: by id, else by name (created at the end), else the last."""
    target = next((b for b in blocks if block_id is not None and b.get("id") == block_id), None)
    if target is None and block_name:
        target = next((b for b in blocks if b.get("name") == block_name), None)
        if target is None:
            target = {"id": _new_id(), "name": block_name, "open": True, "tasks": []}
            blocks.append(target)
    if target is None:
        if not blocks:
            blocks.append({"id": _new_id(), "name": "Задания", "open": True, "tasks": []})
        target = blocks[-1]
    return target


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
                state, approved, reason, rejected_at = _moderation(t)
                entries.append(CatalogEntry(
                    number, str(t.get("name", "")), str(t.get("version", "")),
                    str(t.get("digest", "")), str(b.get("id", "")), str(b.get("name", "")),
                    available=bool(approved) and is_open and not hidden, hidden=hidden,
                    block_open=is_open, state=state, approved_digest=approved, reason=reason,
                    rejected_at=rejected_at, approved_image=str(t.get("approved_image") or "")))
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

    def add_task(self, ref: str, digest: str, *, block_id: str | None = None,  # noqa: PLR0913
                 block_name: str | None = None, hidden: bool = True, auto: bool = False,
                 image: str = "") -> None:
        """
        Publish a task into a block -- HIDDEN by default, so its author can test it first.

        The block is `block_id`, else the one named `block_name` (created, open, at the end if it
        does not exist), else the last block. A task already in the catalog keeps its place and
        its hidden flag when re-published into the same block (or with no block given) -- only
        the digest changes; moving it to an explicitly named other block keeps its flag too.
        (Moving every re-publish to the last block once put a whole catalog into «Архив».)

        Every push is a version to moderate: `pending` (students keep the approved one, if any),
        or straight `approved` when `auto` (the pool's or the author's auto-approval).
        """
        name, _, version = ref.partition(":")
        data = self._load()
        blocks = data.setdefault("blocks", [])

        def is_ref(t: dict) -> bool:
            return f"{t.get('name')}:{t.get('version')}" == ref

        home = next((b for b in blocks for t in b.get("tasks", []) if is_ref(t)), None)
        record = {"name": name, "version": version, "digest": digest, "hidden": hidden,
                  "approved_digest": ""}
        if home is not None:
            old = next(t for t in home["tasks"] if is_ref(t))
            record = {**old, "hidden": bool(old.get("hidden", False)),
                      "approved_digest": _moderation(old)[1], "digest": digest}
        record.update({"state": "approved" if auto else "pending", "reason": "", "rejected_at": 0.0})
        if auto:
            record["approved_digest"] = digest
            record["approved_image"] = image
        if home is not None:
            same = block_id is None and block_name in (None, home.get("name"))
            if same or block_id == home.get("id"):
                home["tasks"] = [record if is_ref(t) else t for t in home["tasks"]]
                self._save(data)
                return
        target = _target_block(blocks, block_id, block_name)
        for b in blocks:   # a ref lives in exactly one block
            b["tasks"] = [t for t in b.get("tasks", []) if not is_ref(t)]
        target.setdefault("tasks", []).append(record)
        self._save(data)

    def _update(self, ref: str, change: Callable[[dict], None]) -> dict | None:
        """Apply `change` to the stored task `ref` (normalized to moderation fields); return it."""
        data = self._load()
        for b in data.get("blocks", []):
            for t in b.get("tasks", []):
                if f"{t.get('name')}:{t.get('version')}" == ref:
                    state, approved, reason, rejected_at = _moderation(t)
                    t.update({"state": state, "approved_digest": approved, "reason": reason,
                              "rejected_at": rejected_at})
                    change(t)
                    self._save(data)
                    return t
        return None

    def approve(self, ref: str, image: str = "") -> str | None:
        """Approve the current version -- its task and its `image` blob; return the task digest."""
        t = self._update(ref, lambda t: t.update({"state": "approved", "reason": "", "rejected_at": 0.0,
                                                  "approved_digest": str(t.get("digest", "")),
                                                  "approved_image": image}))
        return None if t is None else str(t["approved_digest"])

    def mark_pending(self, ref: str) -> bool:
        """Send a task back to approval: a new image alone is a new version too (students keep theirs)."""
        return self._update(ref, lambda t: t.update({"state": "pending", "reason": "",
                                                     "rejected_at": 0.0})) is not None

    def set_approved_image(self, ref: str, image: str) -> None:
        """Pin which image blob is the approved one (a legacy entry learns it on its first copy)."""
        self._update(ref, lambda t: t.update({"approved_image": image}))

    def restore_approved(self, ref: str, image: str) -> None:
        """Back to the approved version after a rejected update expired: approved, its digests."""
        self._update(ref, lambda t: t.update({"state": "approved", "reason": "", "rejected_at": 0.0,
                                              "digest": str(t.get("approved_digest", "")),
                                              "approved_image": image}))

    def expired_rejected(self, now: float, ttl: float = REJECT_TTL) -> list[str]:
        """Rejected at least `ttl` ago but with an approved version: to roll back, not to delete."""
        return [e.ref for e in self.entries()
                if e.state == "rejected" and now - e.rejected_at >= ttl and e.approved_digest]

    def reject(self, ref: str, reason: str, *, now: float) -> bool:
        """Reject the current version (students keep an approved one, if any); False if no such task."""
        return self._update(ref, lambda t: t.update({"state": "rejected", "reason": reason,
                                                     "rejected_at": now})) is not None

    def purge_rejected(self, now: float, ttl: float = REJECT_TTL) -> list[str]:
        """
        Drop never-approved tasks rejected at least `ttl` ago; return their refs.

        A task with an approved version is not dropped -- its rejected UPDATE is (see
        `expired_rejected` / `restore_approved`): students keep the course task.
        """
        gone = [e.ref for e in self.entries()
                if e.state == "rejected" and now - e.rejected_at >= ttl and not e.approved_digest]
        for ref in gone:
            self.remove_task(ref)
        return gone

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

    def set_block_tasks_hidden(self, block_id: str, *, hidden: bool,
                               may: Callable[[str], bool] = lambda _ref: True) -> bool:
        """
        Hide (or show) every task of a block that `may(ref)` allows; return whether the block existed.

        This is how a teacher opens a block's tasks one by one: hide them all, keep the block
        open, then show single tasks with `set_task_hidden`.
        """
        data = self._load()
        for b in data.get("blocks", []):
            if b.get("id") == block_id:
                for t in b.get("tasks", []):
                    if may(f"{t.get('name')}:{t.get('version')}"):
                        t["hidden"] = hidden
                self._save(data)
                return True
        return False

    def move_task(self, ref: str, step: int) -> bool:
        """
        Move a task one place up (`step` < 0) or down; return whether it moved.

        Like the web's ↑/↓: inside a block it swaps with its neighbour; at the block's edge it
        crosses into the previous block (as its last task) or the next one (as its first) --
        an empty block counts. The task keeps its digest and hidden flag; nothing else moves.
        """
        data = self._load()
        blocks = [b for b in data.get("blocks", []) if isinstance(b, dict)]
        for bi, b in enumerate(blocks):
            tasks = b.setdefault("tasks", [])
            for ti, t in enumerate(tasks):
                if f"{t.get('name')}:{t.get('version')}" != ref:
                    continue
                to = ti + (1 if step > 0 else -1)
                if 0 <= to < len(tasks):
                    tasks[ti], tasks[to] = tasks[to], t
                elif step < 0 and bi > 0:
                    blocks[bi - 1].setdefault("tasks", []).append(tasks.pop(ti))
                elif step > 0 and bi < len(blocks) - 1:
                    blocks[bi + 1].setdefault("tasks", []).insert(0, tasks.pop(ti))
                else:
                    return False
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
        stored = {f"{t.get('name')}:{t.get('version')}": t
                  for b in self._load().get("blocks", []) if isinstance(b, dict)
                  for t in b.get("tasks", [])}
        prev = {str(b.get("id")): b for b in self._load().get("blocks", []) if isinstance(b, dict)}
        blocks: list[dict[str, object]] = []
        for b in layout:
            block_id = str(b.get("id") or _new_id())
            was = prev.get(block_id, {})
            tasks = []
            for raw in b.get("tasks", []):
                ref = str(raw)
                if ref not in stored:
                    continue
                tasks.append(dict(stored[ref]))   # digest, hidden and moderation travel with it
            blocks.append({"id": block_id, "name": str(b.get("name", was.get("name", ""))),
                           "open": bool(b.get("open", was.get("open", True))), "tasks": tasks})
        self._save({"blocks": blocks})
