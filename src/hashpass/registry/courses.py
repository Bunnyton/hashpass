"""
Courses: blocks of tasks pinned to image revisions, with an owner, members and proposals (spec §4-§6).

A course is `courses/<owner>/<name>/course.json` (the id is immutable, `owner/name` is its
address). A task in a course is `{repo, tag, n, pinned, hidden, added_by}`: it shows revision
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
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROLES = ("member", "author", "maintainer", "owner")
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
    created_at: str = ""
    rev: int = 0

    @property
    def ref(self) -> str:
        return f"{self.owner}/{self.name}"

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
    known = set(Course.__dataclass_fields__)
    return Course(**{k: v for k, v in raw.items() if k in known})


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

    def get(self, ref: str) -> Course | None:
        try:
            return _course(json.loads(self._path(ref).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    def all(self) -> list[Course]:
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
            yield course
            course.rev += 1
            self._save(course)

    def delete(self, ref: str) -> None:
        path = self._path(ref)
        with contextlib.suppress(OSError):
            path.unlink()
        with contextlib.suppress(OSError):
            (path.parent / ".lock").unlink()
            path.parent.rmdir()

    def courses_with(self, repo: str, tag: str) -> list[Course]:
        """Courses holding the task `repo:tag`."""
        return [course for course in self.all() if course.find_task(repo, tag) is not None]


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


def add_task(course: Course, repo: str, tag: str, n: int, block_id: str, *, by: str) -> dict:  # noqa: PLR0913
    """Put task `repo:tag` (revision `n`) at the end of a block."""
    if course.find_task(repo, tag) is not None:
        msg = f"{repo}:{tag} уже в курсе"
        raise ValueError(msg)
    task = {"repo": repo, "tag": tag, "n": int(n), "pinned": False, "hidden": False, "added_by": by}
    _block(course, block_id)["tasks"].append(task)
    return task


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
            by: str, comment: str, now: float) -> dict:
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
                 "comment": comment[:500], "at": now})
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
            add_task(course, prop["repo"], prop["tag"], prop["n"], block_id, by=prop["by"])
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

def set_member(course: Course, user: str, role: str) -> None:
    if role not in ROLES[:-1]:
        msg = f"роль — {', '.join(ROLES[:-1])}"
        raise ValueError(msg)
    if user == course.owner:
        msg = "владелец остаётся владельцем"
        raise ValueError(msg)
    course.members[user] = role


def remove_member(course: Course, user: str) -> None:
    course.members.pop(user, None)


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
