"""
Courses: blocks of tasks pinned to image revisions, with an owner, members and proposals (spec §4-§6).

A course is `courses/<owner>/<name>/course.json` (the id is immutable, `owner/name` is its
address; a rename moves it, and only the newest address exists). A task in a course is `{repo, tag, n, pinned, hidden, added_by}`: it shows revision
`tag_vN` -- or, with the course's `auto_update` on and the task not pinned, the newest revision
of the tag. Changes others want go through proposals (`add`, `update`, `restore`), one open per
tag; `auto_accept` takes them at once. Private courses admit members by invite link or by an
access request. Writers hold `edit()`: a file lock, a fresh read, `rev` + 1 on save.
"""
import contextlib
import fcntl
import json
import os
import re
import secrets
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hashpass.registry import course_copies as cc
from hashpass.registry import perms

ROLES = ("member", "author", "admin", "owner")   # `maintainer` (before 2026-10-25) reads as `admin`
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VISIBILITIES = ("public", "private")
KINDS = ("add", "update", "restore")
REQUEST_PAUSE = 24 * 60 * 60          # after a rejected access request


class CourseConflictError(RuntimeError):
    """The course changed since the caller read it (`rev` mismatch)."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Course:
    """One course, as stored."""

    id: str
    owner: str
    name: str
    title: str = ""
    description: str = ""
    visibility: str = "public"
    auto_accept: bool = False
    auto_update: bool = True
    invite: str = ""
    members: dict[str, str] = field(default_factory=dict)
    requests: list[dict] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)   # spec 2026-10-23 §4: who changed what, why
    perms: dict[str, list[str]] = field(default_factory=dict)   # spec 2026-10-25 §3: admins' boxes
    extras: dict[str, list[str]] = field(default_factory=dict)   # 2026-10-26: authors' extra rights
    origin: dict = field(default_factory=dict)      # spec 2026-10-31: a mirror's / a fork's parent
    allow_mirrors: bool = True
    allow_forks: bool = False
    merges: list[dict] = field(default_factory=list)   # whole forks offered back to this course
    created_at: str = ""
    rev: int = 0

    @classmethod
    def from_raw(cls, raw: dict) -> "Course":
        """Build a course from its stored JSON; a `maintainer` of old is an `admin`."""
        known = set(cls.__dataclass_fields__)
        course = cls(**{k: v for k, v in raw.items() if k in known})
        course.members = {u: ("admin" if r == "maintainer" else r) for u, r in course.members.items()}
        course.perms = {u: list(b) for u, b in (course.perms or {}).items()
                        if course.members.get(u) == "admin" and isinstance(b, list)}
        course.extras = {u: [e for e in perms.EXTRAS if e in b] for u, b in (course.extras or {}).items()
                         if course.members.get(u) == "author" and isinstance(b, list)}
        return course

    @property
    def ref(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def closed(self) -> bool:
        """A mirror whose owner lost access to its private parent: closed to students (spec 2026-10-31 §5)."""
        return self.kind == "mirror" and bool(self.origin.get("revoked"))

    @property
    def kind(self) -> str:
        """`mirror` (follows a live parent), `fork` (one's own copy; a mirror whose parent is gone), or ""."""
        kind = str(self.origin.get("kind", ""))
        return "fork" if kind == "mirror" and self.origin.get("gone") else kind

    def role_of(self, user: str | None) -> str | None:
        """Return `user`'s role here (`owner` for the owner), or None."""
        if not user:
            return None
        if user == self.owner:
            return "owner"
        return self.members.get(user)

    def tasks(self) -> Iterator[tuple[dict, dict]]:
        """Yield (block, task) in course order."""
        for block in self.blocks:
            for task in block.get("tasks", []):
                yield block, task

    def find_task(self, repo: str, tag: str) -> dict | None:
        return next((t for _b, t in self.tasks() if (t["repo"], t["tag"]) == (repo, tag)), None)


def _course(raw: dict) -> Course:
    return Course.from_raw(raw)


class CourseStore:
    """All courses under `root`."""

    def __init__(self, root: Path) -> None:
        """Open the course store at `root` (created on the first write)."""
        self._root = Path(root)

    def _path(self, ref: str) -> Path:
        owner, _, name = ref.partition("/")
        if not owner or not NAME_RE.match(name) or "/" in owner or owner.startswith("."):
            msg = f"нет такого курса: {ref}"
            raise ValueError(msg)
        return self._root / owner / name / "course.json"

    def _read(self, ref: str) -> Course | None:
        """Return the course as stored (a mirror not caught up)."""
        try:
            return _course(json.loads(self._path(ref).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    def get(self, ref: str) -> Course | None:
        """Return the course; a mirror behind its parent shows the parent's structure (spec 2026-10-31 §2)."""
        course = self._read(ref)
        if course is not None and course.origin and not course.origin.get("gone"):
            self._refresh(course)
        return course

    def _refresh(self, copy: Course, parents: dict[str, Course] | None = None) -> None:
        """
        Bring a copy (in memory) up to its parent.

        The parent's address and title, whether the copy's owner still sees a private parent
        (`revoked`), and a mirror's structure.
        """
        pid = str(copy.origin.get("id", ""))
        parent = parents.get(pid) if parents is not None else self.by_id(pid)
        if parent is None:
            return
        if parent.visibility == "private":
            copy.visibility = "private"                # a copy of a private course never shows more
        revoked = parent.visibility == "private" and parent.role_of(copy.owner) is None
        copy.origin |= {"ref": parent.ref, "owner": parent.owner, "title": parent.title, "revoked": revoked}
        if copy.kind != "mirror" or revoked or cc.structure(parent) == cc.structure(copy):
            return
        cc.apply_structure(copy, cc.structure(parent), source_open=cc.block_open(parent))
        copy.origin["synced_rev"] = parent.rev

    def all_fresh(self) -> list[Course]:
        """Every course as `get()` would give it: copies brought up to their parents (in memory)."""
        raw = self.all()
        by_id = {c.id: c for c in raw}
        fresh = {c.id: _course(asdict(c)) for c in raw}
        for course in fresh.values():
            if course.origin and not course.origin.get("gone"):
                self._refresh(course, by_id)
        return list(fresh.values())

    def all(self) -> list[Course]:
        """Every course as stored."""
        if not self._root.is_dir():
            return []
        out = []
        for path in sorted(self._root.glob("*/*/course.json")):
            with contextlib.suppress(OSError, ValueError, TypeError):
                out.append(_course(json.loads(path.read_text(encoding="utf-8"))))
        return out

    def _save(self, course: Course) -> None:
        path = self._path(course.ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".course-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(course), f, ensure_ascii=False, indent=2)
            Path(tmp).replace(path)
        except BaseException:
            with contextlib.suppress(OSError):
                Path(tmp).unlink()
            raise

    @contextlib.contextmanager
    def _lock(self, ref: str) -> Iterator[None]:
        path = self._path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def create(self, owner: str, name: str, *, title: str = "", visibility: str = "public",
               description: str = "") -> Course:
        """Create a course `owner/name` (name: lowercase latin, digits, dashes)."""
        if not NAME_RE.match(name):
            msg = f"имя курса «{name}»: строчные латинские буквы, цифры и дефис"
            raise ValueError(msg)
        if visibility not in VISIBILITIES:
            msg = "видимость — public или private"
            raise ValueError(msg)
        ref = f"{owner}/{name}"
        with self._lock(ref):
            if self._path(ref).exists():
                msg = f"курс {ref} уже есть"
                raise ValueError(msg)
            course = Course(id=f"c-{secrets.token_hex(6)}", owner=owner, name=name,
                            title=title or name, description=description, visibility=visibility,
                            invite=secrets.token_urlsafe(16), created_at=_now())
            self._save(course)
        self._index(lambda ids: ids.__setitem__(course.id, course.ref))
        return course

    @property
    def _ids_path(self) -> Path:
        return self._root / ".ids.json"

    def _ids(self) -> dict[str, str] | None:
        """Return the id -> ref index, or None when there is none yet."""
        try:
            ids = json.loads(self._ids_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return ids if isinstance(ids, dict) else None

    def _index(self, change: Callable[[dict[str, str]], object]) -> None:
        """Change the id -> ref index under its lock (built from a scan the first time)."""
        self._root.mkdir(parents=True, exist_ok=True)
        with (self._root / ".ids.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                ids = self._ids()
                if ids is None:
                    ids = {c.id: c.ref for c in self.all()}
                change(ids)
                fd, tmp = tempfile.mkstemp(prefix=".ids-", suffix=".tmp", dir=self._root)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(ids, f, ensure_ascii=False)
                Path(tmp).replace(self._ids_path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def by_id(self, course_id: str) -> Course | None:
        """Return the course (as stored) whose immutable id is `course_id`, through the id index."""
        if not course_id:
            return None
        ids = self._ids()
        ref = ids.get(course_id) if ids is not None else None
        course = self._read(ref) if ref else None
        if course is not None and course.id == course_id:
            return course
        if ids is not None and ref is None:
            return None                               # not in a built index: no such course
        found = next((c for c in self.all() if c.id == course_id), None)   # lost or wrong: rebuild
        self._index(lambda ids: (ids.clear(), ids.update({c.id: c.ref for c in self.all()})))
        return found

    def copies_of(self, course_id: str, kind: str | None = None) -> list[Course]:
        """Return the direct mirrors and forks of a course (`kind` -- only those)."""
        return [c for c in self.all() if c.origin.get("id") == course_id and not c.origin.get("gone")
                and (kind is None or c.kind == kind)]

    def root_of(self, course: Course) -> Course:
        """Return what a copy of `course` copies: a mirror's live parent, else the course itself."""
        if course.kind == "mirror":
            return self.by_id(str(course.origin.get("id", ""))) or course
        return course

    def create_copy(self, parent: Course, owner: str, name: str, kind: str, *,  # noqa: PLR0913
                    title: str = "", visibility: str = "public") -> Course:
        """Make `owner/name` a mirror or a fork of `parent` (its structure; the people are the copy's own)."""
        if kind not in ("mirror", "fork"):
            msg = f"неизвестный вид копии: {kind}"
            raise ValueError(msg)
        course = self.create(owner, name, title=title or parent.title, visibility=visibility,
                             description=parent.description)
        with self.edit(course.ref) as copy:
            struct = cc.structure(parent)
            cc.apply_structure(copy, struct, source_open=cc.block_open(parent))
            copy.origin = {"id": parent.id, "kind": kind, "ref": parent.ref, "owner": parent.owner,
                           "title": parent.title, "base_rev": parent.rev, "base": struct,
                           "synced_rev": parent.rev, "gone": False, "revoked": False}
        if self.by_id(parent.id) is None:             # deleted meanwhile: delete() may have missed us
            with self.edit(course.ref) as copy:
                copy.origin["gone"] = True
        return self.get(course.ref) or course

    def rename(self, ref: str, name: str) -> Course:
        """Move a course to `owner/name`; the old address is gone (user 2026-10-27: no legacy names)."""
        if not NAME_RE.match(name):
            msg = f"имя курса «{name}»: строчные латинские буквы, цифры и дефис"
            raise ValueError(msg)
        new = f"{ref.partition('/')[0]}/{name}"
        with self._lock(ref):
            course = self.get(ref)
            if course is None:
                msg = f"нет такого курса: {ref}"
                raise KeyError(msg)
            if new == course.ref:
                return course
            if self._path(new).exists():
                msg = f"курс {new} уже есть"
                raise ValueError(msg)
            self._path(ref).parent.rename(self._path(new).parent)
            course.name = name
            course.rev += 1
            self._save(course)
        self._index(lambda ids: ids.__setitem__(course.id, course.ref))
        return course

    @contextlib.contextmanager
    def edit(self, ref: str, expect_rev: int | None = None) -> Iterator[Course]:
        """Change a course under its lock; `expect_rev` guards against a concurrent edit."""
        with self._lock(ref):
            course = self.get(ref)
            if course is None:
                msg = f"нет такого курса: {ref}"
                raise KeyError(msg)
            if expect_rev is not None and course.rev != expect_rev:
                msg = "курс изменился, пока вы его смотрели — обновите страницу"
                raise CourseConflictError(msg)
            before = cc.structure(course)
            yield course
            course.rev += 1
            self._save(course)
        if cc.structure(course) != before:
            self.propagate(course.id)

    def propagate(self, parent_id: str) -> None:
        """Write a parent's structure into each of its mirrors, each under its own lock."""
        for mirror in self.copies_of(parent_id, "mirror"):
            with contextlib.suppress(KeyError), self.edit(mirror.ref):
                pass                                  # edit() reads through get(): caught up, saved

    def heal(self) -> None:
        """Write every mirror left behind its parent (a server stopped between the two writes)."""
        for course in self.all():
            if course.kind == "mirror":
                fresh = self.get(course.ref)
                if fresh is not None and cc.structure(fresh) != cc.structure(course):
                    with contextlib.suppress(KeyError), self.edit(course.ref):
                        pass

    def delete(self, ref: str) -> None:
        """Remove a course; its copies stay, on their own (`origin.gone`, spec 2026-10-31 §5)."""
        path = self._path(ref)
        gone = self._read(ref)
        with contextlib.suppress(OSError):
            path.unlink()
        with contextlib.suppress(OSError):
            (path.parent / ".lock").unlink()
            path.parent.rmdir()
        if gone is None:
            return
        self._index(lambda ids: ids.pop(gone.id, None))
        for copy in self.copies_of(gone.id):
            with contextlib.suppress(KeyError), self.edit(copy.ref) as cur:
                cur.origin["gone"] = True

    def courses_with(self, repo: str, tag: str) -> list[Course]:
        """Courses holding the task `repo:tag`."""
        return [course for course in self.all_fresh() if course.find_task(repo, tag) is not None]


# -- blocks and tasks --------------------------------------------------------

def _block(course: Course, block_id: str) -> dict:
    block = next((b for b in course.blocks if b["id"] == block_id), None)
    if block is None:
        msg = "такого блока нет в курсе"
        raise ValueError(msg)
    return block


def add_block(course: Course, name: str) -> str:
    """Add an open block at the end; return its id."""
    block_id = secrets.token_hex(4)
    course.blocks.append({"id": block_id, "name": name.strip() or "Блок", "open": True, "tasks": []})
    return block_id


def rename_block(course: Course, block_id: str, name: str) -> None:
    _block(course, block_id)["name"] = name.strip() or "Блок"


def set_block_open(course: Course, block_id: str, *, open_: bool) -> None:
    _block(course, block_id)["open"] = open_


def remove_block(course: Course, block_id: str) -> None:
    """Remove a block -- only an empty one."""
    if _block(course, block_id)["tasks"]:
        msg = "блок не пуст — сначала уберите или перенесите задания"
        raise ValueError(msg)
    course.blocks = [b for b in course.blocks if b["id"] != block_id]
    for block in course.blocks:
        if block_id in block.get("needs", []):
            set_block_needs(course, block["id"], [i for i in block["needs"] if i != block_id])


def set_block_needs(course: Course, block_id: str, needs: Iterable[str]) -> None:
    """
    Make block `block_id` open to a student once every block of `needs` is solved (user 2026-11-01).

    Kept in course order, once each; [] -- no condition (the default). Blocks waiting for each
    other would never open, so that is refused.
    """
    block = _block(course, block_id)
    wanted = set(needs)
    for need in wanted:
        _block(course, need)
    if block_id in wanted:
        msg = "блок не может ждать сам себя"
        raise ValueError(msg)
    after = {b["id"]: set(b.get("needs", [])) for b in course.blocks} | {block_id: wanted}
    seen, todo = set(), list(wanted)
    while todo:                                       # does any needed block wait for this one?
        bid = todo.pop()
        if bid == block_id:
            msg = "блоки ждут друг друга — так ни один не откроется"
            raise ValueError(msg)
        if bid not in seen:
            seen.add(bid)
            todo.extend(after.get(bid, ()))
    block.pop("needs", None)
    if wanted:
        block["needs"] = [b["id"] for b in course.blocks if b["id"] in wanted]


def waiting_for(course: Course, block: dict, passed: set[str]) -> list[str]:
    """Names of the blocks `block` needs that are not solved yet: a task not hidden and not in `passed`."""
    by_id = {b["id"]: b for b in course.blocks}
    return [by_id[i]["name"] for i in block.get("needs", []) if i in by_id
            and any(f"{t['repo']}:{t['tag']}" not in passed for t in by_id[i]["tasks"] if not t.get("hidden"))]


def add_task(course: Course, repo: str, tag: str, n: int, block_id: str, *, by: str,  # noqa: PLR0913
             after: str = "") -> dict:
    """
    Put task `repo:tag` (revision `n`) where the person puts it (user 2026-10-23).

    `after` -- "" the end of the block, "^" its start, "owner/x:tag" right after that task.
    """
    if course.find_task(repo, tag) is not None:
        msg = f"{repo}:{tag} уже в курсе"
        raise ValueError(msg)
    task = {"repo": repo, "tag": tag, "n": int(n), "pinned": False, "hidden": False, "added_by": by}
    tasks = _block(course, block_id)["tasks"]
    refs = [f"{t['repo']}:{t['tag']}" for t in tasks]
    if after == "^":
        tasks.insert(0, task)
    elif after in refs:
        tasks.insert(refs.index(after) + 1, task)
    else:
        tasks.append(task)
    return task


def parse_place(place: str) -> tuple[str, str]:
    """Split a form's `place` -- "<block id>" or "<block id>|^" or "<block id>|owner/x:tag"."""
    block_id, _, after = str(place).partition("|")
    return block_id, after


def remove_task(course: Course, repo: str, tag: str) -> bool:
    for block in course.blocks:
        kept = [t for t in block["tasks"] if (t["repo"], t["tag"]) != (repo, tag)]
        if len(kept) != len(block["tasks"]):
            block["tasks"] = kept
            return True
    return False


def move_task(course: Course, repo: str, tag: str, step: int) -> bool:
    """Move a task one place up (-1) or down (+1) inside its block."""
    for block in course.blocks:
        tasks = block["tasks"]
        idx = next((i for i, t in enumerate(tasks) if (t["repo"], t["tag"]) == (repo, tag)), None)
        if idx is None:
            continue
        other = idx + step
        if not 0 <= other < len(tasks):
            return False
        tasks[idx], tasks[other] = tasks[other], tasks[idx]
        return True
    return False


def set_layout(course: Course, layout: list[dict]) -> None:
    """Reorder blocks and tasks: `[{id, tasks: ["repo:tag", ...]}]` naming every block and task once."""
    by_block = {b["id"]: b for b in course.blocks}
    by_task = {f"{t['repo']}:{t['tag']}": t for _b, t in course.tasks()}
    seen_blocks = [str(b.get("id", "")) for b in layout]
    seen_tasks = [str(r) for b in layout for r in b.get("tasks", [])]
    if sorted(seen_blocks) != sorted(by_block) or sorted(seen_tasks) != sorted(by_task):
        msg = "раскладка не совпадает с курсом — обновите страницу"
        raise ValueError(msg)
    blocks = []
    for item in layout:
        block = by_block[str(item["id"])]
        block["tasks"] = [by_task[str(r)] for r in item.get("tasks", [])]
        blocks.append(block)
    course.blocks = blocks


def effective_n(course: Course, task: dict, *, latest: int | None) -> int:
    """Return the revision students get: the newest with auto_update on and the task not pinned."""
    if course.auto_update and not task.get("pinned") and latest:
        return max(int(latest), int(task["n"]))
    return int(task["n"])


def pending_updates(course: Course, latest_of: Callable[[str, str], int | None]) -> list[tuple[str, str, int]]:
    """Tasks a newer revision exists for while the course stays on `n` (pinned / no auto_update)."""
    out = []
    for _, task in course.tasks():
        latest = latest_of(task["repo"], task["tag"])
        if latest and latest > int(task["n"]) and (task.get("pinned") or not course.auto_update):
            out.append((task["repo"], task["tag"], int(latest)))
    return out


# -- proposals ---------------------------------------------------------------

def _open_proposal(course: Course, repo: str, tag: str) -> dict | None:
    return next((p for p in course.proposals
                 if p["state"] == "open" and (p["repo"], p["tag"]) == (repo, tag)), None)


def propose(course: Course, kind: str, repo: str, tag: str, n: int, block_id: str, *,  # noqa: PLR0913, PLR0917
            by: str, comment: str, now: float, after: str = "") -> dict:
    """Propose a change for `repo:tag` (one open per tag: a new one refreshes it); auto_accept takes it."""
    if kind not in KINDS:
        msg = f"неизвестный вид предложения: {kind}"
        raise ValueError(msg)
    prop = _open_proposal(course, repo, tag)
    if prop is None:
        prop = {"id": f"p-{secrets.token_hex(4)}", "kind": kind, "repo": repo, "tag": tag,
                "state": "open", "reason": "", "decided_by": "", "decided_at": 0.0}
        course.proposals.append(prop)
    prop.update({"kind": kind, "n": int(n), "block_id": block_id, "by": by,
                 "comment": comment[:500], "at": now} | ({"after": after} if after else {}))
    if course.auto_accept:
        decide(course, prop["id"], accept=True, by="auto", now=now)
    return prop


def decide(course: Course, proposal_id: str, *, accept: bool, by: str, now: float,  # noqa: PLR0913
           reason: str = "") -> dict:
    """Accept (apply it) or reject (with a reason) an open proposal."""
    prop = next((p for p in course.proposals if p["id"] == proposal_id), None)
    if prop is None or prop["state"] != "open":
        msg = "такого открытого предложения нет"
        raise ValueError(msg)
    if accept:
        task = course.find_task(prop["repo"], prop["tag"])
        if task is not None:
            task["n"] = int(prop["n"])
        else:
            block_id = prop.get("block_id") or ""
            if not any(b["id"] == block_id for b in course.blocks):
                block_id = course.blocks[0]["id"] if course.blocks else add_block(course, "Задания")
            add_task(course, prop["repo"], prop["tag"], prop["n"], block_id, by=prop["by"],
                     after=str(prop.get("after", "")))
    prop.update({"state": "accepted" if accept else "rejected", "reason": reason[:500],
                 "decided_by": by, "decided_at": now})
    return prop


def withdraw(course: Course, proposal_id: str, *, by: str) -> None:
    """Take an open proposal back (its author only)."""
    prop = next((p for p in course.proposals if p["id"] == proposal_id), None)
    if prop is None or prop["state"] != "open":
        msg = "такого открытого предложения нет"
        raise ValueError(msg)
    if prop["by"] != by:
        msg = "отозвать предложение может только его автор"
        raise PermissionError(msg)
    prop["state"] = "withdrawn"


# -- members, requests, invites ----------------------------------------------

def set_member(course: Course, user: str, role: str, boxes: Iterable[str] | None = None, *,
               extras: Iterable[str] | None = None) -> None:
    """Give `user` a role here; an admin's boxes are `boxes`, or kept, or DEFAULT; an author's `extras`."""
    role = "admin" if role == "maintainer" else role       # old clients
    if role not in ROLES[:-1]:
        msg = f"роль — {', '.join(ROLES[:-1])}"
        raise ValueError(msg)
    if user == course.owner:
        msg = "владелец остаётся владельцем"
        raise ValueError(msg)
    course.members[user] = role
    if role != "author":
        course.extras.pop(user, None)
    if role != "admin":
        course.perms.pop(user, None)
    elif boxes is not None:
        course.perms[user] = sorted(perms.clean(list(boxes), default=perms.DEFAULT))
    if role == "author" and extras is not None:
        set_extras(course, user, extras)


def set_extras(course: Course, user: str, extras: Iterable[str]) -> None:
    """Give an author extra rights (perms.EXTRAS, 2026-10-26); none -- the entry goes."""
    if course.members.get(user) != "author":
        msg = "дополнительные права дают автору курса"
        raise ValueError(msg)
    wanted = [e for e in perms.EXTRAS if e in set(extras)]
    if wanted:
        course.extras[user] = wanted
    else:
        course.extras.pop(user, None)


def remove_member(course: Course, user: str) -> None:
    course.members.pop(user, None)
    course.perms.pop(user, None)
    course.extras.pop(user, None)


def request_access(course: Course, user: str, comment: str, *, now: float) -> dict:
    """Ask to join a private course: one open request; a day's pause after a refusal."""
    mine = [r for r in course.requests if r["user"] == user]
    if any(r["state"] == "open" for r in mine):
        msg = "заявка уже отправлена — ждите ответа"
        raise ValueError(msg)
    refused = [r for r in mine if r["state"] == "rejected"]
    if refused and now - float(refused[-1].get("decided_at", 0.0)) < REQUEST_PAUSE:
        msg = "заявку отклонили — новую можно отправить через сутки"
        raise ValueError(msg)
    req = {"user": user, "comment": comment[:500], "state": "open", "at": now,
           "decided_by": "", "decided_at": 0.0}
    course.requests.append(req)
    return req


def decide_request(course: Course, user: str, *, accept: bool, by: str, now: float) -> None:
    req = next((r for r in reversed(course.requests) if r["user"] == user and r["state"] == "open"), None)
    if req is None:
        msg = "открытой заявки нет"
        raise ValueError(msg)
    req.update({"state": "accepted" if accept else "rejected", "decided_by": by, "decided_at": now})
    if accept:
        course.members.setdefault(user, "member")


def join_by_invite(course: Course, user: str, token: str) -> bool:
    """Join with the course's invite link; False for a wrong or old token."""
    if not token or not secrets.compare_digest(token, course.invite):
        return False
    if course.role_of(user) is None:
        course.members[user] = "member"
    return True


def rotate_invite(course: Course) -> None:
    course.invite = secrets.token_urlsafe(16)
