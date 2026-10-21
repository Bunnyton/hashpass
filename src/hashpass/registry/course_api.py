"""
Courses over HTTP (spec 2026-10-21 §4-§7): the JSON API under `/courses`.

Every handler resolves the caller, the course and `access.can(...)` first; course writes go
through `CourseStore.edit` (lock + rev). Tasks reference pool revisions, checked against the
registry (`PoolServer.repo`) when added. Who joined which course is kept in `.enrollments/`.
"""
import json
import time
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Flask, Response, request

from hashpass.registry import courses as cm
from hashpass.registry.access import can
from hashpass.registry.courses import Course, CourseConflictError, CourseStore
from hashpass.registry.revisions import parse_version

if TYPE_CHECKING:
    from hashpass.registry.server import PoolServer

_MAX_TEXT = 2000


class Enrollments:
    """Which courses a user has started: `<root>/<user>.json` = {course_id: at}."""

    def __init__(self, root: Path) -> None:
        """Open (creating on write) the enrollment store at `root`."""
        self._root = Path(root)

    def of(self, user: str) -> dict[str, float]:
        try:
            return dict(json.loads((self._root / f"{user}.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def enroll(self, user: str, course_id: str) -> None:
        data = self.of(user)
        if course_id in data:
            return
        data[course_id] = time.time()
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / f"{user}.json").write_text(json.dumps(data), encoding="utf-8")

    def users_of(self, course_id: str) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.stem for p in self._root.glob("*.json") if course_id in self.of(p.stem))

    def forget(self, user: str) -> None:
        (self._root / f"{user}.json").unlink(missing_ok=True)


class CourseApi:
    """The `/courses` routes, bound to a PoolServer's stores and helpers."""

    def __init__(self, server: "PoolServer") -> None:
        """Bind to `server` (its store root holds `.courses/` and `.enrollments/`)."""
        self.server = server

    @property
    def courses(self) -> CourseStore:
        return CourseStore(Path(self.server.store.root) / ".courses")

    @property
    def enrollments(self) -> Enrollments:
        return Enrollments(Path(self.server.store.root) / ".enrollments")

    # -- wiring -------------------------------------------------------------

    def register(self, app: Flask) -> None:
        rule = app.add_url_rule
        rule("/courses", "courses", self.list_or_create, methods=["GET", "POST"])
        rule("/courses/<owner>/<name>", "course", self.course, methods=["GET", "PUT", "DELETE"])
        rule("/courses/<owner>/<name>/join", "course_join", self.join, methods=["POST"])
        rule("/courses/<owner>/<name>/requests", "course_requests", self.request_access,
             methods=["POST"])
        rule("/courses/<owner>/<name>/requests/<user>", "course_request", self.decide_request,
             methods=["POST"])
        rule("/courses/<owner>/<name>/members/<user>", "course_member", self.member,
             methods=["PUT", "DELETE"])
        rule("/courses/<owner>/<name>/blocks", "course_blocks", self.add_block, methods=["POST"])
        rule("/courses/<owner>/<name>/blocks/<block_id>", "course_block", self.block,
             methods=["PUT", "DELETE"])
        rule("/courses/<owner>/<name>/tasks", "course_tasks", self.add_task, methods=["POST"])
        rule("/courses/<owner>/<name>/tasks/<path:task>", "course_task", self.task,
             methods=["PUT", "DELETE"])
        rule("/courses/<owner>/<name>/proposals/<pid>", "course_proposal", self.proposal,
             methods=["POST"])

    # -- helpers ------------------------------------------------------------

    def _json(self, status: HTTPStatus, payload: dict) -> Response:
        return Response(json.dumps(payload, ensure_ascii=False), status=int(status),
                        mimetype="application/json")

    def _err(self, status: HTTPStatus, message: str) -> Response:
        return self._json(status, {"error": message})

    def _body(self) -> dict:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def _caller(self) -> tuple[str | None, str | None]:
        user = self.server._token_user()                 # noqa: SLF001  (same package)
        return user, (self.server.users.role(user) if user else None)

    def _load(self, owner: str, name: str, action: str) -> tuple[Course | None, str | None, Response | None]:
        """Return the course + caller, or an error: 404/401 when it may not be seen, 403 otherwise."""
        user, role = self._caller()
        course = self.courses.get(f"{owner}/{name}")
        if course is None:
            return None, user, self._err(HTTPStatus.NOT_FOUND, f"нет такого курса: {owner}/{name}")
        if not can(user, role, course, action):
            if not can(user, role, course, "view"):
                status = HTTPStatus.UNAUTHORIZED if user is None else HTTPStatus.FORBIDDEN
                return None, user, self._err(status, "курс закрыт — попросите доступ")
            return None, user, self._err(HTTPStatus.FORBIDDEN, "не хватает прав в этом курсе")
        return course, user, None

    def _edit(self, ref: str, change: Callable[[Course], object]) -> Response | None:
        """Apply `change` under the course lock (`rev` from the body guards); an error -> a response."""
        body = self._body()
        expect = body.get("rev")
        try:
            with self.courses.edit(ref, expect_rev=int(expect) if isinstance(expect, int) else None) as course:
                change(course)
        except CourseConflictError as exc:
            return self._err(HTTPStatus.CONFLICT, str(exc))
        except PermissionError as exc:
            return self._err(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, KeyError) as exc:
            return self._err(HTTPStatus.BAD_REQUEST, str(exc.args[0] if exc.args else exc))
        return None

    def _latest(self, repo: str, tag: str) -> int | None:
        rev = self.server.repo(repo).latest(tag)
        return rev.n if rev else None

    def _summary(self, course: Course, user: str | None) -> dict:
        return {"ref": course.ref, "id": course.id, "owner": course.owner, "name": course.name,
                "title": course.title, "description": course.description,
                "visibility": course.visibility, "role": course.role_of(user)}

    def _view(self, course: Course, user: str | None, role: str | None) -> dict:
        """Return the course as `user` may see it."""
        staff = can(user, role, course, "moderate")
        out = self._summary(course, user) | {"rev": course.rev}
        blocks = []
        for block in course.blocks:
            if not block.get("open", True) and not staff:
                continue
            tasks = []
            for task in block["tasks"]:
                if task.get("hidden") and not staff:
                    continue
                latest = self._latest(task["repo"], task["tag"])
                n = cm.effective_n(course, task, latest=latest)
                row = {"repo": task["repo"], "tag": task["tag"], "ref": f"{task['repo']}:{task['tag']}",
                       "n": n, "revision": f"{task['repo']}:{task['tag']}_v{n}"}
                if staff or task.get("added_by") == user:
                    row |= {"pinned": task.get("pinned", False), "hidden": task.get("hidden", False),
                            "latest": latest, "added_by": task.get("added_by", "")}
                tasks.append(row)
            blocks.append({"id": block["id"], "name": block["name"], "open": block.get("open", True),
                           "tasks": tasks})
        out["blocks"] = blocks
        out["proposals"] = [p for p in course.proposals if staff or p.get("by") == user]
        if staff:
            out["updates"] = [{"repo": r, "tag": t, "latest": n}
                              for r, t, n in cm.pending_updates(course, self._latest)]
            out["requests"] = [r for r in course.requests if r["state"] == "open"]
            out["settings"] = {"auto_accept": course.auto_accept, "auto_update": course.auto_update}
        if can(user, role, course, "admin"):
            out["members"] = course.members
            out["invite"] = course.invite
        return out

    def _peek(self, course: Course, user: str | None) -> dict:
        mine = [r for r in course.requests if r["user"] == user]
        access = "requested" if any(r["state"] == "open" for r in mine) else "request"
        return {"ref": course.ref, "title": course.title, "description": course.description,
                "visibility": course.visibility, "access": access}

    # -- routes ---------------------------------------------------------------

    def list_or_create(self) -> Response:
        user, role = self._caller()
        if request.method == "GET":
            q = request.args.get("q", "").casefold()
            rows = [self._summary(c, user) for c in self.courses.all()
                    if can(user, role, c, "view")
                    and (not q or q in f"{c.ref} {c.title} {c.description}".casefold())]
            return self._json(HTTPStatus.OK, {"courses": rows})
        if user is None:
            return self._err(HTTPStatus.UNAUTHORIZED, "войдите, чтобы создать курс")
        body = self._body()
        try:
            course = self.courses.create(user, str(body.get("name", "")), title=str(body.get("title", "")),
                                         visibility=str(body.get("visibility", "public")),
                                         description=str(body.get("description", ""))[:_MAX_TEXT])
        except ValueError as exc:
            return self._err(HTTPStatus.BAD_REQUEST, str(exc))
        self.enrollments.enroll(user, course.id)
        return self._json(HTTPStatus.CREATED, self._summary(course, user))

    def course(self, owner: str, name: str) -> Response:  # noqa: C901, PLR0911
        if request.method == "GET":
            user, role = self._caller()
            course = self.courses.get(f"{owner}/{name}")
            if course is None:
                return self._err(HTTPStatus.NOT_FOUND, f"нет такого курса: {owner}/{name}")
            if not can(user, role, course, "view"):
                return self._json(HTTPStatus.OK, self._peek(course, user))
            return self._json(HTTPStatus.OK, self._view(course, user, role))
        course, _user, err = self._load(owner, name, "admin")
        if err is not None:
            return err
        if request.method == "DELETE":
            self.courses.delete(course.ref)
            return self._json(HTTPStatus.OK, {"deleted": course.ref})
        body = self._body()
        if body.get("visibility") == "public" and course.visibility == "private":
            private = [f"{t['repo']}:{t['tag']}" for _b, t in course.tasks()
                       if self.server.repo(t["repo"]).visibility == "private"]
            if private:
                return self._err(HTTPStatus.CONFLICT,
                                 f"в курсе приватные образы: {', '.join(private)} — сначала сделайте их публичными")

        def change(c: Course) -> None:
            for key in ("title", "description"):
                if key in body:
                    setattr(c, key, str(body[key])[:_MAX_TEXT])
            if "visibility" in body:
                if body["visibility"] not in cm.VISIBILITIES:
                    msg = "видимость — public или private"
                    raise ValueError(msg)
                c.visibility = body["visibility"]
            for key in ("auto_accept", "auto_update"):
                if key in body:
                    setattr(c, key, bool(body[key]))
            if body.get("rotate_invite"):
                cm.rotate_invite(c)
        err = self._edit(course.ref, change)
        return err or self._json(HTTPStatus.OK, self._summary(self.courses.get(course.ref), _user))

    def join(self, owner: str, name: str) -> Response:
        user, role = self._caller()
        if user is None:
            return self._err(HTTPStatus.UNAUTHORIZED, "войдите, чтобы пройти курс")
        course = self.courses.get(f"{owner}/{name}")
        if course is None:
            return self._err(HTTPStatus.NOT_FOUND, f"нет такого курса: {owner}/{name}")
        if not can(user, role, course, "play"):
            joined: list[bool] = []
            err = self._edit(course.ref, lambda c: joined.append(
                cm.join_by_invite(c, user, str(self._body().get("invite", "")))))
            if err is not None:
                return err
            if not joined[0]:
                return self._err(HTTPStatus.FORBIDDEN, "курс закрыт — нужна ссылка-приглашение или заявка")
        self.enrollments.enroll(user, course.id)
        return self._json(HTTPStatus.OK, {"joined": course.ref})

    def request_access(self, owner: str, name: str) -> Response:
        user, _role = self._caller()
        if user is None:
            return self._err(HTTPStatus.UNAUTHORIZED, "войдите, чтобы попросить доступ")
        if self.courses.get(f"{owner}/{name}") is None:
            return self._err(HTTPStatus.NOT_FOUND, f"нет такого курса: {owner}/{name}")
        comment = str(self._body().get("comment", ""))
        err = self._edit(f"{owner}/{name}", lambda c: cm.request_access(c, user, comment, now=time.time()))
        return err or self._json(HTTPStatus.CREATED, {"requested": f"{owner}/{name}"})

    def decide_request(self, owner: str, name: str, user: str) -> Response:
        course, actor, err = self._load(owner, name, "moderate")
        if err is not None:
            return err
        accept = bool(self._body().get("accept"))
        err = self._edit(course.ref, lambda c: cm.decide_request(c, user, accept=accept, by=actor,
                                                                 now=time.time()))
        if err is None and accept:
            self.enrollments.enroll(user, course.id)
        return err or self._json(HTTPStatus.OK, {"user": user, "accepted": accept})

    def member(self, owner: str, name: str, user: str) -> Response:
        course, _actor, err = self._load(owner, name, "admin")
        if err is not None:
            return err
        if request.method == "DELETE":
            err = self._edit(course.ref, lambda c: cm.remove_member(c, user))
            return err or self._json(HTTPStatus.OK, {"removed": user})
        if not self.server.users.has(user):
            return self._err(HTTPStatus.NOT_FOUND, f"нет пользователя {user}")
        role = str(self._body().get("role", ""))
        err = self._edit(course.ref, lambda c: cm.set_member(c, user, role))
        return err or self._json(HTTPStatus.OK, {"user": user, "role": role})

    def add_block(self, owner: str, name: str) -> Response:
        course, _actor, err = self._load(owner, name, "moderate")
        if err is not None:
            return err
        made: list[str] = []
        err = self._edit(course.ref, lambda c: made.append(cm.add_block(c, str(self._body().get("name", "")))))
        return err or self._json(HTTPStatus.CREATED, {"id": made[0]})

    def block(self, owner: str, name: str, block_id: str) -> Response:
        course, _actor, err = self._load(owner, name, "moderate")
        if err is not None:
            return err
        body = self._body()

        def change(c: Course) -> None:
            if request.method == "DELETE":
                cm.remove_block(c, block_id)
                return
            if "name" in body:
                cm.rename_block(c, block_id, str(body["name"]))
            if "open" in body:
                cm.set_block_open(c, block_id, open_=bool(body["open"]))
        err = self._edit(course.ref, change)
        return err or self._json(HTTPStatus.OK, {"id": block_id})

    def _revision_ok(self, course: Course, user: str, repo: str, tag: str, n: int | None) -> str | int:
        """Return the revision number to use, or a Russian reason it cannot go into this course."""
        idx = self.server.repo(repo)
        rev = idx.get(tag, n) if n else idx.latest(tag)
        if rev is None:
            return f"на пуле нет {repo}:{tag}" + (f"_v{n}" if n else "")
        if idx.visibility == "private":
            if course.visibility != "private":
                return f"{repo} приватный — в публичный курс его не поставить; сделайте образ публичным"
            if not self.server._may_write(user, repo):           # noqa: SLF001
                return f"нет такого образа: {repo}:{tag}"
        return rev.n

    def add_task(self, owner: str, name: str) -> Response:
        course, user, err = self._load(owner, name, "propose")
        if err is not None:
            return err
        body = self._body()
        repo, tag = str(body.get("repo", "")), str(body.get("tag", ""))
        tag = parse_version(tag)[0] if tag else tag
        n = self._revision_ok(course, user, repo, tag, int(body["n"]) if body.get("n") else None)
        if isinstance(n, str):
            return self._err(HTTPStatus.BAD_REQUEST, n)
        block_id = str(body.get("block_id", ""))
        role = self.server.users.role(user)
        direct = can(user, role, course, "add")
        out: list[dict] = []

        def change(c: Course) -> None:
            bid = block_id if any(b["id"] == block_id for b in c.blocks) else (
                c.blocks[0]["id"] if c.blocks else cm.add_block(c, "Задания"))
            if direct:
                out.append(cm.add_task(c, repo, tag, n, bid, by=user))
            else:
                out.append(cm.propose(c, "add", repo, tag, n, bid, by=user,
                                      comment=str(body.get("comment", "")), now=time.time()))
        err = self._edit(course.ref, change)
        if err is not None:
            return err
        return self._json(HTTPStatus.CREATED, {"task": out[0]} if direct else {"proposal": out[0]})

    def task(self, owner: str, name: str, task: str) -> Response:  # noqa: C901
        repo, _, tag = task.rpartition(":")
        course, user, err = self._load(owner, name, "add")
        if err is not None:
            return err
        role = self.server.users.role(user)
        moderator = can(user, role, course, "moderate")
        current = course.find_task(repo, tag)
        if current is None:
            return self._err(HTTPStatus.NOT_FOUND, f"в курсе нет {repo}:{tag}")
        if not moderator and current.get("added_by") != user:
            return self._err(HTTPStatus.FORBIDDEN, "менять чужое задание может сопровождающий курса")
        if request.method == "DELETE":
            err = self._edit(course.ref, lambda c: cm.remove_task(c, repo, tag))
            return err or self._json(HTTPStatus.OK, {"removed": f"{repo}:{tag}"})
        body = self._body()
        new_n = None
        if "n" in body:
            got = self._revision_ok(course, user, repo, tag, int(body["n"]) if body["n"] else None)
            if isinstance(got, str):
                return self._err(HTTPStatus.BAD_REQUEST, got)
            new_n = got

        def change(c: Course) -> None:
            t = c.find_task(repo, tag)
            if t is None:
                msg = f"в курсе нет {repo}:{tag}"
                raise KeyError(msg)
            if new_n is not None:
                t["n"] = new_n
            for key in ("hidden", "pinned"):
                if key in body:
                    t[key] = bool(body[key])
            if body.get("move") in (-1, 1):
                cm.move_task(c, repo, tag, int(body["move"]))
        err = self._edit(course.ref, change)
        return err or self._json(HTTPStatus.OK, {"task": self.courses.get(course.ref).find_task(repo, tag)})

    def proposal(self, owner: str, name: str, pid: str) -> Response:
        course, user, err = self._load(owner, name, "propose")
        if err is not None:
            return err
        body = self._body()
        action = str(body.get("action", ""))
        if action == "withdraw":
            err = self._edit(course.ref, lambda c: cm.withdraw(c, pid, by=user))
            return err or self._json(HTTPStatus.OK, {"id": pid, "state": "withdrawn"})
        if action not in ("accept", "reject"):
            return self._err(HTTPStatus.BAD_REQUEST, "action — accept, reject или withdraw")
        if not can(user, self.server.users.role(user), course, "moderate"):
            return self._err(HTTPStatus.FORBIDDEN, "решает сопровождающий или владелец курса")
        err = self._edit(course.ref, lambda c: cm.decide(c, pid, accept=action == "accept", by=user,
                                                         now=time.time(),
                                                         reason=str(body.get("reason", ""))))
        return err or self._json(HTTPStatus.OK, {"id": pid, "state": action + "ed"})
