"""
A course's people outside `course.json`: the students' comments to the course and pending invitations.

Kept apart from the course file on purpose: a course is copied (mirrors, forks), its students'
words and invitations are not (spec 2026-11-04-приглашения-в-курс). Both are small JSON files,
written under a lock and replaced atomically, like `.enrollments`.
"""
import contextlib
import fcntl
import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

MAX_NOTE = 500


class _Files:
    """`<root>/<key>.json` = a dict, read freely, changed under `<root>/.<key>.lock`."""

    def __init__(self, root: Path) -> None:
        """Files live in `root` (created on the first write)."""
        self.root = Path(root)

    def read(self, key: str) -> dict:
        try:
            data = json.loads((self.root / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def change(self, key: str, fn: Callable[[dict], object]) -> object:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / f".{key}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.read(key)
            result = fn(data)
            tmp = self.root / f".{key}.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.root / f"{key}.json")
            return result

    def names(self) -> Iterator[str]:
        if self.root.is_dir():
            yield from sorted(p.stem for p in self.root.glob("*.json"))


class CourseNotes:
    """What each student told the course's team on joining: `<course_id>.json` = {user: {text, at}}."""

    def __init__(self, root: Path) -> None:
        """Open the store at `root`."""
        self._files = _Files(root)

    def of_course(self, course_id: str) -> dict[str, str]:
        return {u: str(n.get("text", "")) for u, n in self._files.read(course_id).items() if isinstance(n, dict)}

    def set(self, course_id: str, user: str, text: str, *, now: float | None = None) -> None:
        """Keep `text` as `user`'s note to the course; an empty one removes it."""
        text = text.strip()[:MAX_NOTE]

        def put(data: dict) -> None:
            if text:
                data[user] = {"text": text, "at": time.time() if now is None else now}
            else:
                data.pop(user, None)
        self._files.change(course_id, put)

    def has(self, course_id: str, user: str) -> bool:
        return user in self._files.read(course_id)


class CourseInvites:
    """Invitations waiting for an answer: `<user>.json` = {course_id: {by, at}}."""

    def __init__(self, root: Path) -> None:
        """Open the store at `root`."""
        self._files = _Files(root)

    def of(self, user: str) -> dict[str, dict]:
        return {c: r for c, r in self._files.read(user).items() if isinstance(r, dict)}

    def add(self, user: str, course_id: str, *, by: str, now: float | None = None) -> bool:
        """Invite `user`; False when an invitation is already waiting."""
        def put(data: dict) -> bool:
            if course_id in data:
                return False
            data[course_id] = {"by": by, "at": time.time() if now is None else now}
            return True
        return bool(self._files.change(user, put))

    def drop(self, user: str, course_id: str) -> bool:
        """Remove the invitation (accepted, declined, revoked); whether there was one."""
        if course_id not in self._files.read(user):
            return False
        return self._files.change(user, lambda data: data.pop(course_id, None) is not None) is True

    def to_course(self, course_id: str) -> dict[str, dict]:
        """Who waits for an answer from this course: {user: {by, at}}."""
        return {u: rec for u in self._files.names() if (rec := self.of(u).get(course_id))}


def migrate_profile_comments(notes: CourseNotes, members_of: Iterator[tuple[str, list[str]]],
                             comment_of: Callable[[str], str], marker: Path) -> int:
    """
    Once: a student's private profile comment becomes their note to every course they are in.

    User 2026-11-04: «смигрируй правильно эти данные из приватного комментария в комменты курса».
    Not destructive -- the profile keeps its comment (the pool's admins still see it); a note
    already written stays. `members_of` yields (course_id, students); returns how many notes.
    """
    if marker.exists():
        return 0
    made = 0
    for course_id, students in members_of:
        for user in students:
            text = comment_of(user).strip()
            if text and not notes.has(course_id, user):
                notes.set(course_id, user, text)
                made += 1
    marker.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        marker.write_text(f"{made}\n", encoding="utf-8")
    return made
