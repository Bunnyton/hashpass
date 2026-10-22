"""
One search page, GitHub-like (user 2026-10-22): `/search?q=&type=`.

Users, courses and images are on the left, each with how many it found; results of the chosen
kind are on the right.

Each kind shows only what the viewer may see: courses by `view`, images by repository
visibility. Users are found by login by anyone; their comment is private (user 2026-10-22:
«виден только при работе с курсом») -- never shown or searched here.
"""
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Flask, Response, request

from hashpass.registry.access import can
from hashpass.registry.revisions import revision_version
from hashpass.registry.web import _env

if TYPE_CHECKING:
    from hashpass.registry.server import PoolServer

_LIMIT = 200
_KINDS = (("users", "Пользователи"), ("courses", "Курсы"), ("images", "Образы"))


class SearchWeb:
    """The search page, bound to a PoolServer."""

    def __init__(self, server: "PoolServer") -> None:
        """Bind to `server` (courses, repositories and users are read from it)."""
        self.server = server

    def register(self, app: Flask) -> None:
        app.add_url_rule("/search", "web_search", self.search, methods=["GET"])

    def search(self) -> Response:
        user = self.server._session_user()          # noqa: SLF001  (same package)
        role = self.server.users.role(user) if user else None
        q = request.args.get("q", "").strip()
        found = {"users": self._users(q), "courses": self._courses(user, role, q),
                 "images": self._images(user, q)}
        kinds = [(k, title) for k, title in _KINDS if k in found]
        kind = request.args.get("type", "")
        if kind not in found:
            kind = next((k for k, _t in kinds if found[k]), "courses")
        html = _env.get_template("search.html.j2").render(
            title="Поиск — hashpass", nav=True, active="/search", q=q, kind=kind,
            kinds=[{"key": k, "title": t, "count": len(found[k])} for k, t in kinds],
            rows=found[kind][:_LIMIT], more=max(0, len(found[kind]) - _LIMIT),
            may_profile=role in ("author", "admin"))
        return self.server._html(html)               # noqa: SLF001

    def _courses(self, user: str | None, role: str | None, q: str) -> list[dict]:
        api = self.server.course_api
        rows = []
        for course in api.courses.all():
            if not can(user, role, course, "view"):
                continue
            if q.casefold() not in f"{course.ref} {course.title} {course.description}".casefold():
                continue
            rows.append(api._summary(course, user) | {"tasks": sum(1 for _ in course.tasks())})  # noqa: SLF001
        return sorted(rows, key=lambda r: (r["role"] is None, r["ref"]))

    def _images(self, user: str | None, q: str) -> list[dict]:
        root = Path(self.server.store.root) / ".repos"
        rows = []
        for index in sorted(root.glob("*/*/repo.json")) if root.is_dir() else []:
            name = f"{index.parent.parent.name}/{index.parent.name}"
            if q.casefold() not in name.casefold() or not self.server._may_see_repo(user, name):  # noqa: SLF001
                continue
            repo = self.server.repo(name)
            tags = []
            for tag in repo.tags():
                latest = repo.latest(tag)
                if latest is not None:
                    ref = f"{name}:{revision_version(tag, latest.n)}"
                    task = self.server.store.exists(ref) and (
                        self.server.store.get(ref).layer.parent / "task").exists()
                    tags.append({"tag": tag, "n": latest.n, "ref": ref, "task": task, "at": latest.at})
            if tags:
                rows.append({"name": name, "visibility": repo.visibility, "fork_of": repo.fork_of,
                             "tags": tags, "task": any(t["task"] for t in tags)})
        return rows

    def _users(self, q: str) -> list[dict]:
        """Logins containing `q` -- only the login, never the private comment."""
        return [{"user": p["user"]} for p in sorted(self.server.users.all_users(), key=lambda p: str(p["user"]))
                if q.casefold() in str(p["user"]).casefold()]
