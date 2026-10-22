"""
Course pages (spec 2026-10-21 §11): `/c` (list + create) and `/c/<owner>/<name>` (the course).

Pages are server-rendered from the same data the JSON API serves (`CourseApi._view`); every
action on them is a `fetch` into that API (static/api.js), so permissions live in one place.
"""
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote

from flask import Flask, Response, request

from hashpass.registry.access import can
from hashpass.registry.web import _env, render_profile

if TYPE_CHECKING:
    from hashpass.registry.server import PoolServer

_ROLE_RU = {"owner": "владелец", "maintainer": "сопровождающий", "author": "автор", "member": "участник"}


def render_courses(rows: list[dict], *, q: str, signed_in: str | None, message: str = "") -> str:
    """Render the course list page: search, the viewer's and public courses, «create»."""
    return _env.get_template("courses.html.j2").render(
        title="Курсы — hashpass", nav=True, active="/c", rows=rows, q=q, signed_in=signed_in,
        role_ru=_ROLE_RU, message=message)


def render_course(view: dict, **ctx: object) -> str:
    """Render one course page (what is shown depends on the viewer's rights in `ctx`)."""
    return _env.get_template("course.html.j2").render(
        title=f"{view.get('title') or view['ref']} — hashpass", nav=True, active="/c", c=view,
        role_ru=_ROLE_RU, **ctx)


class CourseWeb:
    """The course pages, bound to a PoolServer."""

    def __init__(self, server: "PoolServer") -> None:
        """Bind to `server` (its CourseApi is the data source)."""
        self.server = server

    def register(self, app: Flask) -> None:
        app.add_url_rule("/c", "web_courses", self.courses, methods=["GET"])
        app.add_url_rule("/c/<owner>/<name>", "web_course", self.course, methods=["GET"])
        app.add_url_rule("/c/<owner>/<name>/u/<login>", "web_course_student", self.student, methods=["GET"])

    def student(self, owner: str, name: str, login: str) -> Response:
        """One student inside a course: its tasks with status, tries, time -- the course's staff."""
        user, role = self._viewer()
        course = self.server.course_api.courses.get(f"{owner}/{name}")
        if course is None or not self.server.users.has(login):
            return self.server._empty(HTTPStatus.NOT_FOUND)                     # noqa: SLF001
        if user is None:
            return self.server._redirect(f"/web/login?next={quote(request.path, safe='')}")  # noqa: SLF001
        if not can(user, role, course, "add"):
            return self.server._empty(HTTPStatus.FORBIDDEN)                     # noqa: SLF001
        entries = [{"ref": f"{t['repo']}:{t['tag']}", "number": i}
                   for i, (_b, t) in enumerate(course.tasks(), 1)]
        attempts = self.server.attempts()
        attempts.prune(login)
        return self.server._html(render_profile(                                 # noqa: SLF001
            self.server.users.get(login) or {"user": login}, entries,
            self.server.progress().get(login), attempts.by_task(login),
            course={"ref": course.ref, "title": course.title}))

    def _viewer(self) -> tuple[str | None, str | None]:
        user = self.server._session_user()          # noqa: SLF001  (same package)
        return user, (self.server.users.role(user) if user else None)

    def courses(self) -> Response:
        user, role = self._viewer()
        api = self.server.course_api
        q = request.args.get("q", "").strip()
        rows = []
        for course in api.courses.all():
            if not can(user, role, course, "view"):
                continue
            if q and q.casefold() not in f"{course.ref} {course.title} {course.description}".casefold():
                continue
            rows.append(api._summary(course, user) | {"tasks": sum(1 for _ in course.tasks())})  # noqa: SLF001
        rows.sort(key=lambda r: (r["role"] is None, r["ref"]))
        return self.server._html(render_courses(rows, q=q, signed_in=user))  # noqa: SLF001

    def course(self, owner: str, name: str) -> Response:
        user, role = self._viewer()
        api = self.server.course_api
        course = api.courses.get(f"{owner}/{name}")
        if course is None:
            return self.server._html(  # noqa: SLF001
                render_courses([], q="", signed_in=user, message=f"Курса {owner}/{name} нет."),
                status=HTTPStatus.NOT_FOUND)
        may = {a: can(user, role, course, a) for a in ("view", "play", "propose", "add", "moderate", "admin")}
        view = api._view(course, user, role) if may["view"] else api._peek(course, user)  # noqa: SLF001
        pool = self.server._pool_url()                                         # noqa: SLF001
        link = f"{pool}/c/{course.ref}"
        invite_link = f"{link}?invite={quote(course.invite)}" if may["admin"] else ""
        students = self._students(course) if may["add"] else []
        joined = user is not None and course.id in api.enrollments.of(user)
        return self.server._html(render_course(  # noqa: SLF001
            view, may=may, signed_in=user, link=link, invite_link=invite_link, pool=pool,
            curl_flags="-fsSLk" if pool.startswith("https://") else "-fsSL",
            invite=request.args.get("invite", ""), students=students, joined=joined,
            api=f"/courses/{course.ref}", next_url=quote(request.full_path.rstrip("?"), safe="")))

    def _students(self, course: object) -> list[dict]:
        """Who started the course and how far they got in it (its tasks only)."""
        api = self.server.course_api
        refs = [f"{t['repo']}:{t['tag']}" for _b, t in course.tasks()]
        rows = []
        for student in api.enrollments.users_of(course.id):
            if course.role_of(student) in ("owner", "maintainer", "author"):
                continue                                  # staff are not students of their course
            progress = self.server.progress().get(student)
            done = [r for r in refs if (progress.get(r) or {}).get("status") == "passed"]
            profile = self.server.users.get(student) or {}
            cells = []
            for i, r in enumerate(refs, 1):
                status = (progress.get(r) or {}).get("status", "")
                mark, word = ("✓", "решено") if status == "passed" else (("◐", "начато") if status else ("·", "не начато"))
                cells.append({"n": i, "ref": r, "mark": mark, "word": word, "cls": status or "none"})
            rows.append({"user": student, "comment": profile.get("comment", ""),
                         "done": len(done), "total": len(refs),
                         "pct": round(100 * len(done) / len(refs)) if refs else 0, "cells": cells})
        return sorted(rows, key=lambda r: (-r["done"], r["user"]))
