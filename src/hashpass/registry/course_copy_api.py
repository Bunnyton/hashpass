"""
Mirrors and forks of a course over HTTP (spec 2026-10-31): making them, pulling, merging back.

A mirror follows its parent's tasks and keeps its own people; a fork is its owner's course that
remembers where it came from. Copies are made of what a mirror mirrors (its root); whether one
may is the root's say for a mirror and the course's own for a fork of a fork.
"""
import time
from http import HTTPStatus
from typing import TYPE_CHECKING

from flask import Flask, Response, request

from hashpass.registry import course_copies as cc
from hashpass.registry import course_merges as mg
from hashpass.registry.access import can

if TYPE_CHECKING:
    from hashpass.registry.course_api import CourseApi
    from hashpass.registry.courses import Course
    from hashpass.registry.server import PoolServer

_NOT_ALLOWED = {"mirror": "автор курса не разрешает зеркала", "fork": "автор курса не разрешает форки"}


class CopyApi:
    """The `/courses/<o>/<n>/mirror|fork|sync|merge(s)` routes, beside `CourseApi`."""

    def __init__(self, server: "PoolServer") -> None:
        """Bind to `server`; course storage and helpers are its `course_api`'s."""
        self.server = server

    @property
    def api(self) -> "CourseApi":
        return self.server.course_api

    def register(self, app: Flask) -> None:
        rule = app.add_url_rule
        rule("/courses/<owner>/<name>/mirror", "course_mirror", lambda owner, name: self.copy(owner, name, "mirror"),
             methods=["POST"])
        rule("/courses/<owner>/<name>/fork", "course_fork", lambda owner, name: self.copy(owner, name, "fork"),
             methods=["POST"])
        rule("/courses/<owner>/<name>/copies", "course_copies", self.copies, methods=["GET"])
        rule("/courses/<owner>/<name>/sync", "course_sync", self.sync, methods=["GET", "POST"])
        rule("/courses/<owner>/<name>/merge", "course_offer", self.offer, methods=["POST"])
        rule("/courses/<owner>/<name>/merges", "course_merges", self.merges, methods=["GET"])
        rule("/courses/<owner>/<name>/merges/<mid>", "course_merge", self.decide, methods=["POST"])

    def _unfit(self, parent: "Course", user: str, snapshot: dict) -> str:
        """Why a task the snapshot brings may not go into `parent` (its visibility), or ""."""
        for block in snapshot["blocks"]:
            for task in block["tasks"]:
                if parent.find_task(task["repo"], task["tag"]) is not None:
                    continue
                said = self.api._revision_ok(parent, user, task["repo"], task["tag"], task["n"])  # noqa: SLF001
                if isinstance(said, str):
                    return said
        return ""

    def offer(self, owner: str, name: str) -> Response:
        """Offer the whole fork to its parent: one open request per fork, a new offer refreshes it."""
        fork, parent, user, err = self._fork_parent(owner, name)
        if err is not None:
            return err
        unfit = self._unfit(parent, user, cc.structure(fork))
        if unfit:
            return self.api._err(HTTPStatus.CONFLICT, unfit)                  # noqa: SLF001
        made: list[dict] = []
        comment = str(self.api._body().get("comment", ""))                    # noqa: SLF001
        try:
            with self.api.courses.edit(parent.ref) as cur:
                made.append(mg.offer(cur, fork, by=user, comment=comment, now=time.time()))
        except ValueError as exc:
            return self.api._err(HTTPStatus.CONFLICT, str(exc))               # noqa: SLF001
        return self.api._json(HTTPStatus.CREATED, {"merge": self._row(parent, made[0])})  # noqa: SLF001

    def _row(self, parent: "Course", req: dict) -> dict:
        row = {k: v for k, v in req.items() if k not in ("base", "snapshot")}
        return row | {"stale": mg.stale(parent, req) if req["state"] == "open" else False,
                      "changes": [c | {"text": cc.describe(c)} for c in mg.changes(parent, req)]}

    def merges(self, owner: str, name: str) -> Response:
        """Return the requests the caller may see: the course's `content` people -- all, an author -- theirs."""
        course, user, err = self.api._load(owner, name, "view")              # noqa: SLF001
        if err is not None:
            return err
        staff = can(user, self.server.pool_perms(user), course, "content")
        rows = [self._row(course, r) for r in mg.shown(course, user, staff=staff, now=time.time())]
        return self.api._json(HTTPStatus.OK, {"merges": rows[::-1]})        # noqa: SLF001

    def decide(self, owner: str, name: str, mid: str) -> Response:
        """`merge` / `reject` (the parent's `content`), `withdraw` (the request's author)."""
        action = str(self.api._body().get("action", ""))                     # noqa: SLF001
        course, user, err = self.api._load(owner, name, "view" if action == "withdraw" else "content")  # noqa: SLF001
        if err is not None:
            return err
        req = next((r for r in course.merges if r["id"] == mid), None)
        if req is None or action not in ("merge", "reject", "withdraw"):
            return self.api._err(HTTPStatus.NOT_FOUND, "такого запроса нет")   # noqa: SLF001
        if action == "merge" and (unfit := self._unfit(course, user or "", req["snapshot"])):
            return self.api._err(HTTPStatus.CONFLICT, unfit)                  # noqa: SLF001
        reason = str(self.api._body().get("reason", ""))                      # noqa: SLF001
        done: list[dict] = []
        try:
            with self.api.courses.edit(course.ref) as cur:
                if action == "withdraw":
                    mg.withdraw(cur, mid, by=user or "")
                    done.append(next(r for r in cur.merges if r["id"] == mid))
                else:
                    done.append(mg.decide(cur, mid, accept=action == "merge", by=user or "", now=time.time(),
                                          reason=reason))
                    if action == "merge":
                        self.api._history(cur, by=user or "", what=f"слияние из {req['from_ref']} от {req['by']}")  # noqa: SLF001
        except PermissionError as exc:
            return self.api._err(HTTPStatus.FORBIDDEN, str(exc))              # noqa: SLF001
        except ValueError as exc:
            return self.api._err(HTTPStatus.CONFLICT, str(exc))               # noqa: SLF001
        if action == "merge":
            self._level(req["from_id"], self.api.courses.get(course.ref))
        return self.api._json(HTTPStatus.OK, {"merge": self._row(self.api.courses.get(course.ref), done[0])})  # noqa: SLF001

    def _level(self, fork_id: str, parent: "Course") -> None:
        """After a merge the fork's base is the parent as it is now: nothing left to pull."""
        fork = self.api.courses.by_id(fork_id)
        if fork is None:
            return
        with self.api.courses.edit(fork.ref) as cur:
            cur.origin |= {"base": cc.structure(parent), "base_rev": parent.rev}

    def page(self, course: "Course", user: str | None) -> dict:
        """Return what the course page shows about copies to `user` (the web's one source, spec 2026-10-31 §7)."""
        pool = self.server.pool_perms(user)
        source = self.api.courses.root_of(course)
        sees = user is not None and can(user, pool, course, "view") and can(user, pool, source, "view")
        content = can(user, pool, course, "content")
        out: dict = {"mirror": course.kind == "mirror", "source_private": "private" in (
                         source.visibility, course.visibility),
                     "may_mirror": sees and source.allow_mirrors, "may_fork": sees and source.allow_forks,
                     "sync": None, "my_request": None,
                     "merges": [self._row(course, r) for r in mg.shown(course, user, staff=content, now=time.time())][::-1]}
        parent = None if course.kind != "fork" or course.origin.get("gone") or course.origin.get("revoked") \
            else self.api.courses.by_id(str(course.origin.get("id", "")))
        if content and parent is not None:
            theirs = cc.structure(parent)
            base = course.origin.get("base") or theirs
            _merged, conflicts = cc.merge3(base, cc.structure(course), theirs)
            out["sync"] = {"changes": [cc.describe(c) for c in cc.diff(base, theirs)],
                           "conflicts": [cc.describe(c) for c in conflicts]}
            mine = [r for r in parent.merges if r["from_id"] == course.id]
            out["my_request"] = self._row(parent, mine[-1]) if mine else None
        if content:
            copies = self.api.courses.copies_of(course.id)
            for kind in ("mirror", "fork"):
                these = [c for c in copies if c.kind == kind]
                out[f"{kind}s"] = {"n": len(these),
                                   "students": sum(len(self.api.enrollments.users_of(c.id)) for c in these)}
        return out

    def _fork_parent(self, owner: str, name: str) -> tuple["Course | None", "Course | None", str, Response | None]:
        """Return (fork, its parent, caller) for the fork's `content` people, or an error."""
        fork, user, err = self.api._load(owner, name, "content")         # noqa: SLF001
        if err is not None:
            return None, None, "", err
        if not fork.origin or fork.kind != "fork":
            return None, None, "", self.api._err(HTTPStatus.BAD_REQUEST, "это не форк")  # noqa: SLF001
        parent = None if fork.origin.get("gone") else self.api.courses.by_id(str(fork.origin.get("id", "")))
        if parent is None:
            return None, None, "", self.api._err(HTTPStatus.BAD_REQUEST, "исходный курс удалён")  # noqa: SLF001
        if fork.origin.get("revoked"):
            return None, None, "", self.api._err(HTTPStatus.FORBIDDEN, "нет доступа к исходному курсу")  # noqa: SLF001
        return fork, parent, user or "", None

    def behind(self, fork: "Course") -> int | None:
        """How many changes the fork's parent made since the fork last pulled, or None (not a live fork)."""
        if fork.kind != "fork" or fork.origin.get("gone") or fork.origin.get("revoked"):
            return None
        parent = self.api.courses.by_id(str(fork.origin.get("id", "")))
        return len(cc.diff(fork.origin.get("base") or cc.structure(parent), cc.structure(parent))) if parent else None

    def sync(self, owner: str, name: str) -> Response:
        """GET: what the parent changed and what would conflict; POST: bring it in (spec 2026-10-31 §3.1)."""
        fork, parent, user, err = self._fork_parent(owner, name)
        if err is not None:
            return err
        theirs = cc.structure(parent)
        base = fork.origin.get("base") or theirs
        changes = cc.diff(base, theirs)
        if request.method == "GET":
            _merged, conflicts = cc.merge3(base, cc.structure(fork), theirs)
            return self.api._json(HTTPStatus.OK, {                            # noqa: SLF001
                "behind": len(changes), "changes": [c | {"text": cc.describe(c)} for c in changes],
                "conflicts": [c | {"text": cc.describe(c)} for c in conflicts]})
        said: dict = {}

        def pull(c: "Course") -> None:
            merged, conflicts = cc.merge3(base, cc.structure(c), theirs)
            cc.apply_structure(c, merged, source_open=cc.block_open(parent))
            c.origin |= {"base": theirs, "base_rev": parent.rev}
            said.update(applied=len(changes) - len(conflicts),
                        conflicts=[x | {"text": cc.describe(x)} for x in conflicts])

        err = self.api._edit(fork.ref, pull, by=user, check_rev=False,     # noqa: SLF001
                             what=lambda _c: f"подтянуто из {parent.ref}: изменений {said['applied']}, "
                                             f"конфликтов {len(said['conflicts'])}")
        return err or self.api._json(HTTPStatus.OK, said)                   # noqa: SLF001

    def copies(self, owner: str, name: str) -> Response:
        """Return the course's own mirrors and forks with their students, for «delete them too?» (`content`)."""
        course, _user, err = self.api._load(owner, name, "content")      # noqa: SLF001
        if err is not None:
            return err
        copies = self.api.courses.copies_of(course.id)
        return self.api._json(HTTPStatus.OK, {                            # noqa: SLF001
            "mirrors": [c.ref for c in copies if c.kind == "mirror"],
            "forks": [c.ref for c in copies if c.kind == "fork"],
            "students": {c.ref: len(self.api.enrollments.users_of(c.id)) for c in copies}})

    def after_settings(self, course: "Course", user: str, body: dict) -> dict:
        """
        Carry a parent's settings change over to its copies (spec 2026-10-31 §5).

        Private now -> its public copies turn private; `delete_existing: ["mirrors", "forks"]`
        (with copies switched off) -> those copies are deleted. Returns `{"deleted": [...]}`.
        """
        copies = self.api.courses.copies_of(course.id)
        if course.visibility == "private":
            for copy in copies:
                if copy.visibility != "private":
                    self.api._edit(copy.ref, lambda c: setattr(c, "visibility", "private"), by=user,  # noqa: SLF001
                                   what="исходный курс стал приватным — курс тоже", check_rev=False)
        wanted = body.get("delete_existing")
        if not isinstance(wanted, list):
            return {}
        kinds = {"mirrors": "mirror", "forks": "fork"}
        doomed = [c for c in copies if any(kinds.get(str(w)) == c.kind for w in wanted)]
        for copy in doomed:
            self.api.courses.delete(copy.ref)
        return {"deleted": [c.ref for c in doomed]}

    def copy(self, owner: str, name: str, kind: str) -> Response:  # noqa: PLR0911
        """Make a mirror or a fork of `owner/name` in the caller's namespace."""
        course, user, err = self.api._load(owner, name, "view")        # noqa: SLF001  (one package)
        if err is not None:
            return err
        if user is None:
            return self.api._err(HTTPStatus.UNAUTHORIZED, "войдите, чтобы скопировать курс")  # noqa: SLF001
        source = self.api.courses.root_of(course)
        pool = self.server.pool_perms(user)
        if not can(user, pool, source, "view"):
            return self.api._err(HTTPStatus.FORBIDDEN, "исходный курс закрыт — попросите доступ")  # noqa: SLF001
        if not (source.allow_mirrors if kind == "mirror" else source.allow_forks):
            return self.api._err(HTTPStatus.FORBIDDEN, _NOT_ALLOWED[kind])  # noqa: SLF001
        body = self.api._body()                                        # noqa: SLF001
        private = "private" in (source.visibility, course.visibility)
        visibility = str(body.get("visibility") or ("private" if private else "public"))
        if private and visibility != "private":
            return self.api._err(HTTPStatus.BAD_REQUEST, "копия приватного курса — только приватная")  # noqa: SLF001
        try:
            made = self.api.courses.create_copy(source, user, str(body.get("name", "")), kind,
                                                title=str(body.get("title", "")), visibility=visibility)
        except ValueError as exc:
            return self.api._err(HTTPStatus.BAD_REQUEST, str(exc))     # noqa: SLF001
        self.api.enrollments.enroll(user, made.id)
        return self.api._json(HTTPStatus.CREATED, self.api._summary(made, user))  # noqa: SLF001
