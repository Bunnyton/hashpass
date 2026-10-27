"""
Courses over HTTP (spec 2026-10-21 §4-§7): the JSON API under `/courses`.

Every handler resolves the caller, the course and `access.can(...)` first; course writes go
through `CourseStore.edit` (lock + rev). Tasks reference pool revisions, checked against the
registry (`PoolServer.repo`) when added. Who joined which course is kept in `.enrollments/`.
"""
import fcntl
import json
import os
import time
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Flask, Response, request

from hashpass.registry import courses as cm
from hashpass.registry import perms
from hashpass.registry.access import can, course_perms, sees_hidden
from hashpass.registry.config import save_config
from hashpass.registry.courses import Course, CourseConflictError, CourseStore
from hashpass.registry.revisions import parse_version

if TYPE_CHECKING:
    from hashpass.registry.server import PoolServer

_HISTORY_KEEP = 500           # a course remembers this many changes
_HISTORY_SHOWN = 100
_ROLE_RU = {"member": "участник", "author": "автор", "admin": "админ", "owner": "владелец"}
_MAX_TEXT = 2000


def _rights_said(boxes: list[str] | None, extras: list[str]) -> str:
    """Say a member's rights for the course history: « (Люди и доступ)», « (+ прогресс курса)»."""
    said = f" ({', '.join(perms.LABELS[k] for k in boxes)})" if boxes else ""
    return said + (f" (+ {', '.join(perms.EXTRA_LABELS[e].lower() for e in extras)})" if extras else "")


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
        """Mark that `user` started `course_id` (locked, atomic: parallel joins keep each other)."""
        self._root.mkdir(parents=True, exist_ok=True)
        with (self._root / f".{user}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.of(user)
            if course_id in data:
                return
            data[course_id] = time.time()
            tmp = self._root / f".{user}.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self._root / f"{user}.json")

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
        rule("/courses/<owner>/<name>/layout", "course_layout", self.layout, methods=["PUT"])
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
        user, _role = self._caller()
        course = self.courses.get(f"{owner}/{name}")
        if course is None:
            return None, user, self._err(HTTPStatus.NOT_FOUND, f"нет такого курса: {owner}/{name}")
        if not can(user, self.server.pool_perms(user), course, action):
            if not can(user, self.server.pool_perms(user), course, "view"):
                status = HTTPStatus.UNAUTHORIZED if user is None else HTTPStatus.FORBIDDEN
                return None, user, self._err(status, "курс закрыт — попросите доступ")
            return None, user, self._err(HTTPStatus.FORBIDDEN, "не хватает прав в этом курсе")
        return course, user, None

    def _edit(self, ref: str, change: Callable[[Course], object], *, by: str = "",
              what: str | Callable[[Course], str] = "", check_rev: bool = True) -> Response | None:
        """
        Apply `change` under the course lock (`rev` from the body guards); an error -> a response.

        With `what`: the change goes into the course's history in the same write -- who, what
        (said in words), the body's `comment` (spec 2026-10-23 §4).
        """
        body = self._body()
        expect = body.get("rev") if check_rev else None
        try:
            with self.courses.edit(ref, expect_rev=int(expect) if isinstance(expect, int) else None) as course:
                change(course)
                text = what(course) if callable(what) else what
                if text:
                    last = course.history[-1].get("n", len(course.history)) if course.history else 0
                    course.history.append({"at": time.time(), "by": by, "what": text, "n": int(last) + 1,
                                           "comment": str(body.get("comment", ""))[:_MAX_TEXT]})
                    del course.history[:-_HISTORY_KEEP]
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

    def _view(self, course: Course, user: str | None, _role: str | None) -> dict:
        """Return the course as `user` may see it."""
        staff = can(user, self.server.pool_perms(user), course, "content")
        sees = sees_hidden(user, self.server.pool_perms(user), course)
        out = self._summary(course, user) | {"rev": course.rev}
        blocks = []
        for block in course.blocks:
            tasks = []
            for task in block["tasks"]:
                own = bool(user) and task.get("added_by") == user      # one's own task, hidden or not
                if (task.get("hidden") or not block.get("open", True)) and not (sees or own):
                    continue
                latest = self._latest(task["repo"], task["tag"])
                n = cm.effective_n(course, task, latest=latest)
                rev = self.server.repo(task["repo"]).get(task["tag"], n)
                row = {"repo": task["repo"], "tag": task["tag"], "ref": f"{task['repo']}:{task['tag']}",
                       "n": n, "revision": f"{task['repo']}:{task['tag']}_v{n}",
                       "at": rev.at if rev else ""}       # when this version was pushed
                if staff or task.get("added_by") == user:
                    row |= {"pinned": task.get("pinned", False), "hidden": task.get("hidden", False),
                            "latest": latest, "added_by": task.get("added_by", "")}
                tasks.append(row)
            if tasks or block.get("open", True) or sees:
                blocks.append({"id": block["id"], "name": block["name"], "open": block.get("open", True),
                               "tasks": tasks})
        out["blocks"] = blocks
        out["proposals"] = [p for p in course.proposals if staff or p.get("by") == user]
        if staff:
            out["updates"] = [{"repo": r, "tag": t, "latest": n}
                              for r, t, n in cm.pending_updates(course, self._latest)]
            out["settings"] = {"auto_accept": course.auto_accept, "auto_update": course.auto_update}
        out["members"] = course.members                 # who is in: everyone who sees the course
        out["extras"] = course.extras                   # authors' extra rights (2026-10-26)
        # each change is a version of the course, numbered once (entries from before had no number)
        out["history"] = [h if "n" in h else h | {"n": i}
                          for i, h in reversed(list(enumerate(course.history, 1)))][:_HISTORY_SHOWN]
        if can(user, self.server.pool_perms(user), course, "people"):
            out["invite"] = course.invite
            out["requests"] = [r for r in course.requests if r["state"] == "open"]
        out["perms"] = {u: sorted(course_perms(course, u)) for u, r in course.members.items() if r == "admin"}
        return out

    def _peek(self, course: Course, user: str | None) -> dict:
        mine = [r for r in course.requests if r["user"] == user]
        access = "requested" if any(r["state"] == "open" for r in mine) else "request"
        return {"ref": course.ref, "title": course.title, "description": course.description,
                "visibility": course.visibility, "access": access}

    # -- routes ---------------------------------------------------------------

    def list_or_create(self) -> Response:
        user, _role = self._caller()
        if request.method == "GET":
            q = request.args.get("q", "").casefold()
            rows = [self._summary(c, user) for c in self.courses.all()
                    if can(user, self.server.pool_perms(user), c, "view")
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
            if not can(user, self.server.pool_perms(user), course, "view"):
                return self._json(HTTPStatus.OK, self._peek(course, user))
            return self._json(HTTPStatus.OK, self._view(course, user, role))
        course, _user, err = self._load(owner, name, "delete" if request.method == "DELETE" else "content")
        if err is not None:
            return err
        if request.method == "DELETE":
            self.courses.delete(course.ref)
            return self._json(HTTPStatus.OK, {"deleted": course.ref})
        body = self._body()
        renamed = str(body.get("name") or course.name) != course.name
        if renamed:
            if isinstance(body.get("rev"), int) and body["rev"] != course.rev:
                return self._err(HTTPStatus.CONFLICT, "курс изменился, пока вы его смотрели — обновите страницу")
            course, err = self._rename(course, _user, str(body["name"]))
            if err is not None:
                return err
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
        said = [w for k, w in (("title", "название"), ("description", "описание"), ("visibility", "видимость"),
                               ("auto_accept", "приём предложений"), ("auto_update", "автообновление"))
                if k in body]
        err = self._edit(course.ref, change, by=_user, check_rev=not renamed,
                         what=f"настройки: {', '.join(said)}" if said else "")
        return err or self._json(HTTPStatus.OK, self._summary(self.courses.get(course.ref), _user))

    def _rename(self, course: Course, user: str | None, name: str) -> tuple[Course, Response | None]:
        """Give a course a new address (the owner's call, as deleting it); the old one stops existing."""
        if not can(user, self.server.pool_perms(user), course, "delete"):
            return course, self._err(HTTPStatus.FORBIDDEN, "сменить адрес курса может только владелец")
        old = course.ref
        try:
            course = self.courses.rename(old, name)
        except (ValueError, KeyError) as exc:
            return course, self._err(HTTPStatus.BAD_REQUEST, str(exc.args[0] if exc.args else exc))
        self.server.progress().rename_course(old, course.ref)    # results earned in it stay in it
        if self.server.config.default_course == old:              # old clients' course follows it
            self.server.config.default_course = course.ref
            if self.server.config_path is not None:
                save_config(self.server.config_path, self.server.config)
        err = self._edit(course.ref, lambda _c: None, by=user or "", what=f"адрес: {old} → {course.ref}",
                         check_rev=False)
        return course, err

    def join(self, owner: str, name: str) -> Response:
        user, _role = self._caller()
        if user is None:
            return self._err(HTTPStatus.UNAUTHORIZED, "войдите, чтобы пройти курс")
        course = self.courses.get(f"{owner}/{name}")
        if course is None:
            return self._err(HTTPStatus.NOT_FOUND, f"нет такого курса: {owner}/{name}")
        if not can(user, self.server.pool_perms(user), course, "play"):
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
        course, actor, err = self._load(owner, name, "people")
        if err is not None:
            return err
        accept = bool(self._body().get("accept"))
        err = self._edit(course.ref, lambda c: cm.decide_request(c, user, accept=accept, by=actor,
                                                                 now=time.time()),
                         by=actor, what=f"{'принята' if accept else 'отклонена'} заявка {user}")
        if err is None and accept:
            self.enrollments.enroll(user, course.id)
        return err or self._json(HTTPStatus.OK, {"user": user, "accepted": accept})

    def member(self, owner: str, name: str, user: str) -> Response:  # noqa: PLR0911
        """
        Give `user` a role here, or take it away (spec 2026-10-25 §3); an author's extras (2026-10-26).

        Making, unmaking or re-boxing an admin is the `admins` box, and only with boxes the caller
        holds itself; any other role is `people`. An author's extras need `people` and the box
        behind each (perms.EXTRA_NEEDS). Nobody changes its own role.
        """
        course, actor, err = self._load(owner, name, "view")
        if err is not None:
            return err
        body = self._body()
        role = str(body.get("role") or "")
        if not role and "extras" in body and request.method == "PUT":
            role = course.role_of(user) or ""             # only the author's extras change
        role = "admin" if role == "maintainer" else role               # old clients
        held = course_perms(course, actor) | self.server.pool_perms(actor)
        boxes = body.get("perms") if isinstance(body.get("perms"), list) else None
        admin_change = course.role_of(user) == "admin" or (request.method != "DELETE" and role == "admin")
        if user == actor:
            return self._err(HTTPStatus.FORBIDDEN, "свою роль не меняют")
        if ("admins" if admin_change else "people") not in held:
            return self._err(HTTPStatus.FORBIDDEN, "не хватает прав в этом курсе")
        wanted = self._admin_boxes(course, user, role, boxes, held)
        extras = self._author_extras(course, user, role, body, held)
        for refused in (wanted, extras):
            if isinstance(refused, Response):
                return refused
        if request.method == "DELETE":
            err = self._edit(course.ref, lambda c: cm.remove_member(c, user), by=actor,
                             what=f"{user} больше не в курсе")
            return err or self._json(HTTPStatus.OK, {"removed": user})
        if not self.server.users.has(user):
            return self._err(HTTPStatus.NOT_FOUND, f"нет пользователя {user}")
        given = sorted(wanted) if role == "admin" else None
        more = [e for e in perms.EXTRAS if e in extras]
        said = _rights_said(given, more)
        err = self._edit(course.ref, lambda c: cm.set_member(c, user, role, given, extras=more), by=actor,
                         what=f"{user} — {_ROLE_RU.get(role, role)}{said}")
        return err or self._json(HTTPStatus.OK, {"user": user, "role": role, "perms": given,
                                                 "extras": more if role == "author" else None})

    def _admin_boxes(self, course: Course, user: str, role: str, boxes: list | None,
                     held: frozenset[str]) -> "frozenset[str] | Response":
        """Return an admin's boxes after this change, or a refusal."""
        # boxes the caller lacks are neither given nor taken (as on the pool; review I1, I4)
        current = course_perms(course, user) if course.role_of(user) == "admin" else frozenset()
        if (request.method == "DELETE" or role != "admin") and not perms.subset(current, held):
            return self._err(HTTPStatus.FORBIDDEN, "у этого админа есть права, которых нет у вас")
        if role != "admin":
            return frozenset()
        if boxes is None:                                 # an old client: keep, or the default
            return current if course.role_of(user) == "admin" else perms.DEFAULT & held
        wanted = perms.clean(boxes, default=frozenset())
        if not perms.subset(wanted - current, held):
            return self._err(HTTPStatus.FORBIDDEN, "нельзя выдать права, которых нет у вас")
        return (wanted & held) | (current - held)

    def _author_extras(self, course: Course, user: str, role: str, body: dict,
                       held: frozenset[str]) -> "frozenset[str] | Response":
        """Return the author's extras after this change (kept ones the caller lacks), or a refusal."""
        givable = perms.givable_extras(held)
        had = frozenset(course.extras.get(user, []))
        asked = body.get("extras") if isinstance(body.get("extras"), list) else None
        if (request.method == "DELETE" or role != "author") and not had <= givable:
            return self._err(HTTPStatus.FORBIDDEN, "у этого автора есть права, которых нет у вас")
        if role != "author":
            if asked:
                return self._err(HTTPStatus.BAD_REQUEST, "дополнительные права дают автору курса")
            return frozenset()
        if asked is None:
            return had
        wanted = frozenset(e for e in asked if e in perms.EXTRAS)
        if not wanted - had <= givable:
            return self._err(HTTPStatus.FORBIDDEN, "нельзя выдать права, которых нет у вас")
        return (wanted & givable) | (had - givable)

    def add_block(self, owner: str, name: str) -> Response:
        course, actor, err = self._load(owner, name, "content")
        if err is not None:
            return err
        made: list[str] = []
        err = self._edit(course.ref, lambda c: made.append(cm.add_block(c, str(self._body().get("name", "")))),
                         by=actor, what=f"новый блок «{self._body().get('name', '')}»")
        return err or self._json(HTTPStatus.CREATED, {"id": made[0]})

    def block(self, owner: str, name: str, block_id: str) -> Response:
        course, actor, err = self._load(owner, name, "content")
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
        was = next((b["name"] for b in course.blocks if b["id"] == block_id), block_id)
        what = (f"удалён блок «{was}»" if request.method == "DELETE"
                else f"блок «{was}» переименован в «{body['name']}»" if "name" in body and body["name"] != was
                else (f"блок «{was}» {'открыт' if body.get('open') else 'скрыт'}" if "open" in body else ""))
        err = self._edit(course.ref, change, by=actor, what=what)
        return err or self._json(HTTPStatus.OK, {"id": block_id})

    def layout(self, owner: str, name: str) -> Response:
        course, actor, err = self._load(owner, name, "content")
        if err is not None:
            return err
        blocks = self._body().get("blocks")
        if not isinstance(blocks, list):
            return self._err(HTTPStatus.BAD_REQUEST, "нужен список блоков")
        err = self._edit(course.ref, lambda c: cm.set_layout(c, blocks), by=actor, what="порядок заданий и блоков")
        return err or self._json(HTTPStatus.OK, {"rev": self.courses.get(course.ref).rev})

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
        block_id, after = cm.parse_place(body["place"]) if body.get("place") else (str(body.get("block_id", "")), "")
        direct = can(user, self.server.pool_perms(user), course, "add")
        out: list[dict] = []

        def change(c: Course) -> None:
            bid = block_id if any(b["id"] == block_id for b in c.blocks) else (
                c.blocks[0]["id"] if c.blocks else cm.add_block(c, "Задания"))
            if direct:
                out.append(cm.add_task(c, repo, tag, n, bid, by=user, after=after))
            else:
                out.append(cm.propose(c, "add", repo, tag, n, bid, by=user,
                                      comment=str(body.get("comment", "")), now=time.time(), after=after))
        block_name = lambda c: next((b["name"] for b in c.blocks if b["id"] == block_id), "")  # noqa: E731
        err = self._edit(course.ref, change, by=user, what=(
            (lambda c: f"добавлено {repo}:{tag} (версия {n})"
             + (f" в блок «{block_name(c)}»" if block_name(c) else "")) if direct else ""))
        if err is not None:
            return err
        return self._json(HTTPStatus.CREATED, {"task": out[0]} if direct else {"proposal": out[0]})

    def task(self, owner: str, name: str, task: str) -> Response:  # noqa: C901
        repo, _, tag = task.rpartition(":")
        course, user, err = self._load(owner, name, "add")
        if err is not None:
            return err
        moderator = can(user, self.server.pool_perms(user), course, "content")
        current = course.find_task(repo, tag)
        if current is None:
            return self._err(HTTPStatus.NOT_FOUND, f"в курсе нет {repo}:{tag}")
        if not moderator and current.get("added_by") != user:
            return self._err(HTTPStatus.FORBIDDEN, "менять чужое задание может админ курса")
        if request.method == "DELETE":
            err = self._edit(course.ref, lambda c: cm.remove_task(c, repo, tag), by=user,
                             what=f"убрано {repo}:{tag}")
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
                t["pinned"] = False         # no pinning by hand (user 2026-10-23): follow the course setting
            for key in ("hidden", "pinned"):
                if key in body:
                    t[key] = bool(body[key])
            if body.get("move") in (-1, 1):
                cm.move_task(c, repo, tag, int(body["move"]))
        said = ([f"{repo}:{tag} → версия {new_n}"] if new_n is not None else []) + [
            f"{repo}:{tag} {w}" for k, on, off in (("hidden", "скрыто", "показано"), ("pinned", "закреплено", "откреплено"))
            if k in body for w in [on if body[k] else off]] + (
            [f"{repo}:{tag} передвинуто"] if body.get("move") in (-1, 1) else [])
        err = self._edit(course.ref, change, by=user, what="; ".join(said))
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
        if not can(user, self.server.pool_perms(user), course, "content"):
            return self._err(HTTPStatus.FORBIDDEN, "решает админ или владелец курса")
        prop = next((p for p in course.proposals if p.get("id") == pid), {})
        err = self._edit(course.ref, lambda c: cm.decide(c, pid, accept=action == "accept", by=user,
                                                         now=time.time(),
                                                         reason=str(body.get("reason", ""))),
                         by=user, what=(f"{'принято' if action == 'accept' else 'отклонено'} предложение "
                                        f"{prop.get('by', '')}: {prop.get('repo', '')}:{prop.get('tag', '')}"
                                        f" (версия {prop.get('n', '')})"))
        return err or self._json(HTTPStatus.OK, {"id": pid, "state": action + "ed"})
