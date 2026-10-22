"""
People and search pages, GitHub-like (user 2026-10-22/23).

`/search?q=&type=` -- users, courses, tasks and images on the left, each with how many it found;
`/u/<login>` -- a user's page (one's own is home): the courses they run, their tasks and their
images apart (a task is an image with a Taskfile, but people look for them separately), the
courses those are used in, and -- on one's own page only -- the courses one takes, with progress.

Everything is shown only as far as the viewer may see: courses by `view`, images by repository
visibility; where an image is used -- all courses to its owner and the admin, else the courses
the viewer may see. The private comment is never shown here (user: «виден только при работе с
курсом»), and users are found by login only.
"""
import re
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Flask, Response, request

from hashpass.registry import courses as course_model
from hashpass.registry.access import can
from hashpass.registry.revisions import revision_version
from hashpass.registry.web import PREPARE, _env

if TYPE_CHECKING:
    from hashpass.registry.server import PoolServer

_LIMIT = 200
_STAFF_ROLES = ("owner", "maintainer", "author")   # a student's own enrolments stay private
_KINDS = (("users", "Пользователи"), ("courses", "Курсы"), ("tasks", "Задания"), ("images", "Образы"))
_ROLE_RU = {"owner": "владелец", "maintainer": "сопровождающий", "author": "автор", "member": "участник"}
_SUMMARY_MAX = 140


def summary(text: str) -> str:
    """Return a README's first line as a one-line «what is this» (headings and markup stripped)."""
    for raw in text.splitlines():
        line = re.sub(r"^#+\s*|[*_`]", "", raw.strip()).strip()
        if line:
            return line if len(line) <= _SUMMARY_MAX else line[:_SUMMARY_MAX - 1].rstrip() + "…"
    return ""


class SearchWeb:
    """The search and user pages, bound to a PoolServer."""

    def __init__(self, server: "PoolServer") -> None:
        """Bind to `server` (courses, repositories and users are read from it)."""
        self.server = server

    def register(self, app: Flask) -> None:
        app.add_url_rule("/search", "web_search", self.search, methods=["GET"])
        app.add_url_rule("/u/<login>", "web_user_page", self.user_page, methods=["GET"])

    def _viewer(self) -> tuple[str | None, str | None]:
        user = self.server._session_user()          # noqa: SLF001  (same package)
        return user, (self.server.users.role(user) if user else None)

    # -- pages ------------------------------------------------------------------

    def search(self) -> Response:
        user, role = self._viewer()
        q = request.args.get("q", "").strip()
        repos = self.repos(user, q)
        found = {"users": self._users(q), "courses": self._courses(user, role, q),
                 "tasks": [r for r in repos if r["task"]], "images": [r for r in repos if not r["task"]]}
        kind = request.args.get("type", "")
        if kind not in found:
            kind = next((k for k, _t in _KINDS if found[k]), "courses")
        html = _env.get_template("search.html.j2").render(
            title="Поиск — hashpass", nav=True, active="/search", q=q, kind=kind,
            kinds=[{"key": k, "title": t, "count": len(found[k])} for k, t in _KINDS],
            rows=found[kind][:_LIMIT], more=max(0, len(found[kind]) - _LIMIT), role_ru=_ROLE_RU)
        return self.server._html(html)               # noqa: SLF001

    def user_page(self, login: str) -> Response:
        """Show a user's page (see the module docstring); one's own page is home."""
        user, role = self._viewer()
        if not self.server.users.has(login):
            return self.server._html(_env.get_template("search.html.j2").render(  # noqa: SLF001
                title="Нет такого пользователя — hashpass", nav=True, active="/search", q=login,
                kind="users", kinds=[], rows=[], more=0, role_ru=_ROLE_RU, missing=login),
                status=HTTPStatus.NOT_FOUND)
        api = self.server.course_api
        viewable = [c for c in api.courses.all() if can(user, role, c, "view")]
        runs = [self._course_row(c, role_of=login) for c in viewable if c.role_of(login) in _STAFF_ROLES]
        repos = self.repos(user, "", owner=login)
        see_all = user == login or role == "admin"
        used: dict[str, dict] = {}
        for r in repos:
            for place in self.where_used(r["name"], None, viewer=user, role=role, see_all=see_all):
                row = used.setdefault(place["course"], {**place, "items": []})
                row["items"].append(f"{place['repo']}:{place['tag']}")
        html = _env.get_template("user.html.j2").render(
            title=f"{login} — hashpass", nav=True, active="/u/" + login if user == login else "",
            login=login, me=user == login, courses=sorted(runs, key=lambda r: r["ref"]),
            tasks=[r for r in repos if r["task"]], images=[r for r in repos if not r["task"]],
            used=sorted(used.values(), key=lambda r: r["course"]),
            taking=self._taking(login) if user == login else [],
            created=(self.server.users.get(login) or {}).get("created_at"), role_ru=_ROLE_RU)
        return self.server._html(html)               # noqa: SLF001

    def explore(self) -> Response:
        """
        Show the home page, a showcase like Docker Hub (user 2026-10-23).

        A big search and what is there -- courses, tasks, images, people -- each a few with
        «все N →» into the search.
        """
        user, role = self._viewer()
        repos = self.repos(user, "")
        found = {"courses": sorted(self._courses(user, role, ""), key=lambda r: (-int(r["tasks"]), r["ref"])),
                 "tasks": [r for r in repos if r["task"]], "images": [r for r in repos if not r["task"]],
                 "users": self._users("")}
        shown = {"courses": 6, "tasks": 9, "images": 6, "users": 24}
        pool = self.server._pool_url().rstrip("/")   # noqa: SLF001
        html = _env.get_template("explore.html.j2").render(
            title="hashpass — задания по Linux", nav=True, active="/", role_ru=_ROLE_RU,
            counts={k: len(v) for k, v in found.items()},
            sections=[(k, t, found[k][:shown[k]]) for k, t in
                      (("courses", "Курсы"), ("tasks", "Задания"), ("images", "Образы"), ("users", "Пользователи"))],
            url=pool, flags="-fsSLk" if pool.startswith("https://") else "-fsSL", prepare=PREPARE)
        return self.server._html(html)               # noqa: SLF001

    # -- data -------------------------------------------------------------------

    def _course_row(self, course: "course_model.Course", *, role_of: str | None) -> dict:
        api = self.server.course_api
        return api._summary(course, role_of) | {"tasks": sum(1 for _ in course.tasks())}  # noqa: SLF001

    def _courses(self, user: str | None, role: str | None, q: str) -> list[dict]:
        rows = [self._course_row(c, role_of=user) for c in self.server.course_api.courses.all()
                if can(user, role, c, "view")
                and q.casefold() in f"{c.ref} {c.title} {c.description}".casefold()]
        return sorted(rows, key=lambda r: (r["role"] is None, r["ref"]))

    def repos(self, user: str | None, q: str, *, owner: str = "*") -> list[dict]:
        """Repositories `user` may see (name contains `q`): newest version per tag, task or image, README line."""
        root = Path(self.server.store.root) / ".repos"
        att = self.server.attachments()
        rows = []
        for index in sorted(root.glob(f"{owner}/*/repo.json")) if root.is_dir() else []:
            name = f"{index.parent.parent.name}/{index.parent.name}"
            if q.casefold() not in name.casefold() or not self.server._may_see_repo(user, name):  # noqa: SLF001
                continue
            repo = self.server.repo(name)
            tags, about = [], ""
            for tag in repo.tags():
                latest = repo.latest(tag)
                if latest is None:
                    continue
                ref = f"{name}:{revision_version(tag, latest.n)}"
                task = self.server.store.exists(ref) and (self.server.store.get(ref).layer.parent / "task").exists()
                tags.append({"tag": tag, "n": latest.n, "ref": ref, "task": task, "at": latest.at})
                about = about or self.about(ref, att)
            if tags:
                rows.append({"name": name, "visibility": repo.visibility, "fork_of": repo.fork_of,
                             "tags": tags, "task": any(t["task"] for t in tags), "about": about})
        return rows

    def about(self, ref: str, att: object = None) -> str:
        """One line about `ref` from its README (attached, or in the sources for older pushes)."""
        att = att or self.server.attachments()
        text = str(att.describe(ref)["description"])
        if not text and self.server._sources_ready(ref):               # noqa: SLF001
            for name in ("README.md", "about.md"):
                try:
                    text = self.server.sources().read(ref, name).decode("utf-8", "replace")
                    break
                except (OSError, ValueError):
                    continue
        return summary(text)

    def where_used(self, repo: str, tag: str | None, *, viewer: str | None, role: str | None,
                   see_all: bool = False) -> list[dict]:
        """
        Every place `repo` (`:tag`) stands in a course: course, block, the version students get.

        `see_all` (the image's owner, the admin) -- every course, private ones too: deleting a
        version would touch them; else only the courses the viewer may see.
        """
        rows = []
        latest_of = self.server.repo(repo)
        for course in self.server.course_api.courses.all():
            if not see_all and not can(viewer, role, course, "view"):
                continue
            for block, task in course.tasks():
                if task["repo"] != repo or (tag is not None and task["tag"] != tag):
                    continue
                latest = latest_of.latest(task["tag"])
                n = course_model.effective_n(course, task, latest=latest.n if latest else None)
                rows.append({"course": course.ref, "title": course.title, "visibility": course.visibility,
                             "block": block.get("name", ""), "repo": repo, "tag": task["tag"], "n": n,
                             "pinned": bool(task.get("pinned")), "hidden": bool(task.get("hidden"))})
        return rows

    def _taking(self, login: str) -> list[dict]:
        """Return the courses `login` takes (enrolled, not staff) with progress -- their own page only."""
        api = self.server.course_api
        progress = self.server.progress().get(login)
        rows = []
        for course in api.courses.all():
            if course.id not in api.enrollments.of(login) or course.role_of(login) in _STAFF_ROLES:
                continue
            refs = [f"{t['repo']}:{t['tag']}" for _b, t in course.tasks() if not t.get("hidden")]
            done = sum(1 for r in refs if (progress.get(r) or {}).get("status") == "passed")
            rows.append({"ref": course.ref, "title": course.title, "visibility": course.visibility,
                         "done": done, "total": len(refs),
                         "pct": round(100 * done / len(refs)) if refs else 0})
        return sorted(rows, key=lambda r: r["ref"])

    def _users(self, q: str) -> list[dict]:
        """Logins containing `q` -- only the login, never the private comment."""
        return [{"user": p["user"]} for p in sorted(self.server.users.all_users(), key=lambda p: str(p["user"]))
                if q.casefold() in str(p["user"]).casefold()]
