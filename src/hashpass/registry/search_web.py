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

from flask import Flask, Response, current_app, has_app_context, request, send_file

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
_AVATAR_MAX = 2 * 1024 * 1024
_AVATAR_KINDS = ((b"\x89PNG\r\n\x1a\n", "png", "image/png"), (b"\xff\xd8\xff", "jpg", "image/jpeg"),
                 (b"GIF8", "gif", "image/gif"), (b"RIFF", "webp", "image/webp"))


def summary(text: str) -> str:
    """Return a README's first line as a one-line «what is this» (headings and markup stripped)."""
    for raw in text.splitlines():
        line = re.sub(r"^#+\s*|[*_`]", "", raw.strip()).strip()
        if line:
            return line if len(line) <= _SUMMARY_MAX else line[:_SUMMARY_MAX - 1].rstrip() + "…"
    return ""


def _has_avatar(login: object) -> bool:
    """Whether `login` has a photo on the pool serving this request (templates' `has_avatar`)."""
    people = current_app.config.get("hp_people") if has_app_context() else None
    return people is not None and people._avatar_file(str(login)) is not None  # noqa: SLF001


class SearchWeb:
    """The search and user pages, bound to a PoolServer."""

    def __init__(self, server: "PoolServer") -> None:
        """Bind to `server` (courses, repositories and users are read from it)."""
        self.server = server

    def register(self, app: Flask) -> None:
        app.add_url_rule("/search", "web_search", self.search, methods=["GET"])
        app.add_url_rule("/u/<login>", "web_user_page", self.user_page, methods=["GET"])
        app.add_url_rule("/u/<login>/avatar", "web_user_avatar", self.avatar, methods=["GET"])
        app.add_url_rule("/web/avatar", "web_avatar_put", self.avatar_put, methods=["POST"])
        app.add_url_rule("/web/avatar/delete", "web_avatar_delete", self.avatar_delete, methods=["POST"])
        app.config["hp_people"] = self                # templates ask the app serving this request
        _env.globals["has_avatar"] = _has_avatar

    # -- profile photo (user 2026-10-23: «фотку в профиль хочу добавлять») --------

    def _avatar_dir(self) -> Path:
        return Path(self.server.store.root) / ".avatars"

    def _avatar_file(self, login: str) -> Path | None:
        if not login or "/" in login or login.startswith("."):
            return None
        return next((p for _m, ext, _t in _AVATAR_KINDS
                     if (p := self._avatar_dir() / f"{login}.{ext}").is_file()), None)

    def avatar(self, login: str) -> Response:
        """Serve a user's photo (anyone who sees the user sees it)."""
        path = self._avatar_file(login)
        if path is None:
            return self.server._empty(HTTPStatus.NOT_FOUND)                  # noqa: SLF001
        mime = next(t for _m, ext, t in _AVATAR_KINDS if path.suffix == f".{ext}")
        resp = send_file(path, mimetype=mime, max_age=300)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    def avatar_put(self) -> Response:
        """Set one's own photo: PNG/JPEG/GIF/WebP up to 2 MB (checked by its first bytes)."""
        user, _role = self._viewer()
        if user is None:
            return self.server._redirect("/web/login")                        # noqa: SLF001
        upload = request.files.get("photo")
        data = upload.read(_AVATAR_MAX + 1) if upload else b""
        kind = next(((ext, t) for magic, ext, t in _AVATAR_KINDS if data.startswith(magic)
                     and (ext != "webp" or data[8:12] == b"WEBP")), None)
        if not data or len(data) > _AVATAR_MAX or kind is None:
            return self.server._redirect("/web/settings?photo=bad")          # noqa: SLF001
        folder = self._avatar_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self._drop_avatar(user)
        tmp = folder / f".{user}.tmp"
        tmp.write_bytes(data)
        tmp.replace(folder / f"{user}.{kind[0]}")
        return self.server._redirect(f"/u/{user}")                           # noqa: SLF001

    def avatar_delete(self) -> Response:
        user, _role = self._viewer()
        if user is None:
            return self.server._redirect("/web/login")                        # noqa: SLF001
        self._drop_avatar(user)
        return self.server._redirect("/web/settings")                        # noqa: SLF001

    def _drop_avatar(self, user: str) -> None:
        for _m, ext, _t in _AVATAR_KINDS:
            (self._avatar_dir() / f"{user}.{ext}").unlink(missing_ok=True)

    def _viewer(self) -> tuple[str | None, str | None]:
        user = self.server._session_user()          # noqa: SLF001  (same package)
        return user, (self.server.users.role(user) if user else None)

    # -- pages ------------------------------------------------------------------

    def search(self) -> Response:
        """Send the old search address home: the home page is the search now (user 2026-10-23)."""
        query = request.query_string.decode("utf-8", "replace")
        return self.server._redirect("/" + (f"?{query}" if query else ""))   # noqa: SLF001

    def _found(self, user: str | None, role: str | None, q: str) -> dict[str, list[dict]]:
        repos = self.repos(user, q)
        return {"users": self._users(q), "courses": self._courses(user, role, q),
                "tasks": [r for r in repos if r["task"]], "images": [r for r in repos if not r["task"]]}

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
            taking=[],
            created=(self.server.users.get(login) or {}).get("created_at"), role_ru=_ROLE_RU)
        return self.server._html(html)               # noqa: SLF001

    def explore(self) -> Response:
        """
        Show the home page, a showcase like Docker Hub (user 2026-10-23).

        A big search and what is there -- courses, tasks, images, people -- each a few with
        «все N →» into the search.
        """
        user, role = self._viewer()
        q = request.args.get("q", "").strip()
        found = self._found(user, role, q)
        found["courses"].sort(key=lambda r: (-int(r["tasks"]), r["ref"]))
        kind = request.args.get("type", "")
        if kind not in found:
            kind = next((k for k, _t in _KINDS if found[k]), "courses")
        shown = {"courses": 6, "tasks": 9, "images": 6, "users": 24}
        pool = self.server._pool_url().rstrip("/")   # noqa: SLF001
        ctx = {"q": q, "kind": kind, "searching": bool(q or request.args.get("type")), "role_ru": _ROLE_RU, "counts": {k: len(v) for k, v in found.items()},
               "kinds": [{"key": k, "title": t, "count": len(found[k])} for k, t in _KINDS],
               "rows": found[kind][:_LIMIT], "more": max(0, len(found[kind]) - _LIMIT),
               "sections": [(k, t, found[k][:shown[k]]) for k, t in
                            (("courses", "Курсы"), ("tasks", "Задания"), ("images", "Образы"),
                             ("users", "Пользователи"))]}
        if request.args.get("partial") == "1":       # live search: only the results part
            return self.server._html(_env.get_template("_results.html.j2").render(**ctx))  # noqa: SLF001
        html = _env.get_template("explore.html.j2").render(
            title="hashpass — задания по Linux" if not q else f"{q} — поиск — hashpass", nav=True,
            active="/", url=pool, flags="-fsSLk" if pool.startswith("https://") else "-fsSL",
            prepare=PREPARE, **ctx)
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
