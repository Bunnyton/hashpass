"""
A task's wiki on the pool (spec 2026-11-03 «wiki заданий»): the client API and the site pages.

Who reads: whoever is signed in and sees the task's repository -- the same rule as its card and
README (user: «wiki ограничено условиями отображения задания»); hiding the sources does not hide
it. Who writes: whoever may push the task. Every write names the version it started from and
goes through `WikiStore.save`, so a stale save is a conflict, never an overwrite.

API (token):  GET /wiki/<ns>/<name>                 -> tar.gz of the newest version, X-Wiki-Version
              POST /wiki/<ns>/<name>?base=N&message= <- tar.gz of the whole local wiki
              POST /wiki/<ns>/<name>/rebase?base=N  <- local tar.gz -> merged tar.gz (writes nothing)
Site (cookie): /web/wiki/<ns>/<name>[/<page>] · /edit · /upload · /delete · /history[/<n>]
"""
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

from flask import Flask, Response, request

from hashpass.registry.web import _env
from hashpass.registry.wiki_render import render_page
from hashpass.registry.wiki_store import (
    MAIN,
    MARKDOWN,
    WikiConflict,
    WikiRejected,
    WikiStore,
    check_file,
    check_path,
    pack,
    unpack,
)

if TYPE_CHECKING:
    from hashpass.registry.server import PoolServer


class WikiWeb:
    """The wiki routes, bound to a PoolServer."""

    def __init__(self, server: "PoolServer") -> None:
        """Bind to `server` (its repositories and access rules)."""
        self.server = server

    def register(self, app: Flask) -> None:
        """Add the API and the site routes."""
        app.add_url_rule("/wiki/<ns>/<name>", "wiki_api", self.api, methods=["GET", "POST"])
        app.add_url_rule("/wiki/<ns>/<name>/rebase", "wiki_api_rebase", self.api_rebase, methods=["POST"])
        app.add_url_rule("/web/wiki/<ns>/<name>", "web_wiki_home", self.home, methods=["GET"])
        app.add_url_rule("/web/wiki/<ns>/<name>/edit", "web_wiki_edit", self.edit, methods=["GET", "POST"])
        app.add_url_rule("/web/wiki/<ns>/<name>/upload", "web_wiki_upload", self.upload, methods=["POST"])
        app.add_url_rule("/web/wiki/<ns>/<name>/delete", "web_wiki_delete", self.delete, methods=["POST"])
        app.add_url_rule("/web/wiki/<ns>/<name>/history", "web_wiki_history", self.history, methods=["GET"])
        app.add_url_rule("/web/wiki/<ns>/<name>/history/<int:n>", "web_wiki_version", self.version,
                         methods=["GET"])
        app.add_url_rule("/web/wiki/<ns>/<name>/<path:page>", "web_wiki_page", self.page, methods=["GET"])

    # -- access ---------------------------------------------------------------

    def store(self, repo: str) -> WikiStore:
        """Open the wiki of repository `repo`."""
        return self.server.wiki(repo)

    def _sees(self, user: str | None, repo: str) -> bool:
        idx = self.server.repo(repo)
        return user is not None and idx.exists and self.server._may_see_repo(user, repo)  # noqa: SLF001

    def _writes(self, user: str | None, repo: str) -> bool:
        return user is not None and self.server.repo(repo).exists and self.server._may_write(user, repo)  # noqa: SLF001

    @staticmethod
    def _same_site() -> bool:
        """Refuse a form posted from another site (beside the SameSite=Lax cookie)."""
        if request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        origin = request.headers.get("Origin")
        return not origin or urlsplit(origin).netloc == request.host

    # -- API ------------------------------------------------------------------

    def api(self, ns: str, name: str) -> Response:  # noqa: PLR0911  (one refusal per reason)
        """GET the newest wiki as tar.gz; POST a whole local wiki on top of version `base`."""
        repo = f"{ns}/{name}"
        user = self.server._token_user()                       # noqa: SLF001
        try:
            store = self.store(repo)
        except ValueError:
            return self.server._empty(HTTPStatus.BAD_REQUEST)  # noqa: SLF001
        if user is None:
            return self.server._empty(HTTPStatus.UNAUTHORIZED)  # noqa: SLF001
        if not self._sees(user, repo):
            return self.server._not_found(repo)                # noqa: SLF001
        if request.method == "GET":
            if not store.exists():
                return self.server._json(HTTPStatus.NOT_FOUND, {"error": f"у {repo} нет wiki"})  # noqa: SLF001
            resp = self.server._blob(HTTPStatus.OK, pack(store.files()))  # noqa: SLF001
            resp.headers["X-Wiki-Version"] = str(store.head())
            return resp
        if not self._writes(user, repo):
            return self.server._json(HTTPStatus.FORBIDDEN, {  # noqa: SLF001
                "error": f"wiki {repo} правят владелец и соавторы задания"})
        base = request.args.get("base", type=int, default=0)
        try:
            local = unpack(request.get_data())
            changes = store.local_changes(base, local)
            n = store.save(base, changes, by=user, message=request.args.get("message", ""))
        except WikiRejected as exc:
            return self.server._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})  # noqa: SLF001
        except WikiConflict as exc:
            return self.server._json(HTTPStatus.CONFLICT, {"error": str(exc), "paths": exc.paths,  # noqa: SLF001
                                                           "head": store.head()})
        changed = next((v["changed"] for v in store.versions() if v["n"] == n), []) if n > base else []
        return self.server._json(HTTPStatus.OK, {"n": n, "changed": changed})  # noqa: SLF001

    def api_rebase(self, ns: str, name: str) -> Response:
        """Return the newest wiki with the local changes on top (tar.gz); 409 on a page conflict."""
        repo = f"{ns}/{name}"
        user = self.server._token_user()                       # noqa: SLF001
        if user is None:
            return self.server._empty(HTTPStatus.UNAUTHORIZED)  # noqa: SLF001
        try:
            store = self.store(repo)
        except ValueError:
            return self.server._empty(HTTPStatus.BAD_REQUEST)  # noqa: SLF001
        if not self._sees(user, repo):
            return self.server._not_found(repo)                # noqa: SLF001
        base, keep = request.args.get("base", type=int, default=0), request.args.get("keep") == "mine"
        try:
            local = unpack(request.get_data())
            clash = store.conflicts(base, local)
            head, merged = store.rebase(base, local, keep_mine=keep)
        except WikiRejected as exc:
            return self.server._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})  # noqa: SLF001
        except WikiConflict as exc:
            return self.server._json(HTTPStatus.CONFLICT, {"error": str(exc), "paths": exc.paths,  # noqa: SLF001
                                                           "head": store.head()})
        resp = self.server._blob(HTTPStatus.OK, pack(merged))  # noqa: SLF001
        resp.headers["X-Wiki-Version"] = str(head)
        resp.headers["X-Wiki-Conflict"] = ",".join(clash)
        return resp

    # -- site -----------------------------------------------------------------

    def _open(self, ns: str, name: str, *, write: bool = False) -> tuple[str, str | None, WikiStore | None, Response | None]:
        """Resolve the viewer and the wiki, or the response that refuses (login / 404 / 403)."""
        repo = f"{ns}/{name}"
        user = self.server._session_user()                     # noqa: SLF001
        if user is None:
            return repo, None, None, self.server._redirect(f"/web/login?next={quote(request.full_path, safe='')}")  # noqa: SLF001
        try:
            store = self.store(repo)
        except ValueError:
            return repo, user, None, self.server._web_not_found(repo)  # noqa: SLF001
        if not self._sees(user, repo):
            return repo, user, None, self.server._web_not_found(repo)  # noqa: SLF001
        if write and (not self._writes(user, repo) or not self._same_site()):
            return repo, user, None, self.server._html(  # noqa: SLF001
                _env.get_template("wiki.html.j2").render(title="Нет прав — hashpass", nav=True, active="",
                                                        repo=repo, forbidden=True), HTTPStatus.FORBIDDEN)
        return repo, user, store, None

    def _ctx(self, repo: str, user: str, store: WikiStore, **more: object) -> dict:
        idx = self.server.repo(repo)
        tag = next(iter(idx.tags()), "")
        files = store.names()
        return {"nav": True, "active": "", "repo": repo, "head": store.head(), "card": f"{repo}:{tag}" if tag else repo,
                "pages": sorted(p for p in files if p.endswith(".md")),
                "pictures": sorted(p for p in files if not p.endswith(".md")),
                "may_edit": self._writes(user, repo), **more}

    def home(self, ns: str, name: str) -> Response:
        """Send the wiki's address to its main page (relative links resolve from there)."""
        return self.server._redirect(f"/web/wiki/{ns}/{name}/{MAIN}")  # noqa: SLF001

    def page(self, ns: str, name: str, page: str) -> Response:
        """Show one page (`?v=N` -- an older version) or serve a picture as itself."""
        repo, user, store, refused = self._open(ns, name)
        if refused is not None:
            return refused
        version = request.args.get("v", type=int)
        try:
            data = store.read(page, version)
        except (FileNotFoundError, WikiRejected):
            if page == MAIN and not store.exists():
                return self.server._html(_env.get_template("wiki.html.j2").render(  # noqa: SLF001
                    title=f"Wiki {repo} — hashpass", empty=True, **self._ctx(repo, user, store)))
            return self.server._web_not_found(f"{repo}/{page}")  # noqa: SLF001
        kind = check_file(page, data)
        if kind != MARKDOWN:
            resp = Response(data, status=200, mimetype=kind)
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Content-Security-Policy"] = "default-src 'none'"
            return resp
        body, tags, title = render_page(data.decode("utf-8"))
        return self.server._html(_env.get_template("wiki.html.j2").render(  # noqa: SLF001
            title=f"{title or page} — wiki {repo} — hashpass", body=body, tags=tags, page_title=title,
            page=page, version=version, **self._ctx(repo, user, store)))

    def _edit_form(self, repo: str, user: str, store: WikiStore, page: str, text: str, *,  # noqa: PLR0913
                   status: HTTPStatus = HTTPStatus.OK, conflict: list[str] | None = None, error: str = "",
                   message: str = "") -> Response:
        return self.server._html(_env.get_template("wiki_edit.html.j2").render(  # noqa: SLF001
            title=f"Правка {page} — wiki {repo} — hashpass", page=page, text=text, base=store.head(),
            conflict=conflict or [], error=error, message=message, **self._ctx(repo, user, store)), status)

    def edit(self, ns: str, name: str) -> Response:
        """GET: the editor of a page (a new one too). POST: save it on top of `base`."""
        repo, user, store, refused = self._open(ns, name, write=True)
        if refused is not None:
            return refused
        page = (request.values.get("page") or MAIN).strip()
        if request.method == "GET":
            try:
                text = store.read(page).decode("utf-8") if store.exists() else ""
            except (FileNotFoundError, WikiRejected):
                text = ""
            return self._edit_form(repo, user, store, page, text)
        text = request.form.get("text", "").replace("\r\n", "\n")
        message = request.form.get("message", "")
        try:
            check_path(page)
            if not page.endswith(".md"):
                raise WikiRejected(f"{page}: в редакторе правятся только страницы .md")  # noqa: EM102, TRY003, TRY301
            store.save(request.form.get("base", type=int, default=0), {page: text.encode("utf-8")},
                       by=user, message=message)
        except WikiConflict as exc:
            return self._edit_form(repo, user, store, page, text, status=HTTPStatus.CONFLICT,
                                   conflict=exc.paths, message=message)
        except WikiRejected as exc:
            return self._edit_form(repo, user, store, page, text, status=HTTPStatus.BAD_REQUEST,
                                   error=str(exc), message=message)
        return self.server._redirect(f"/web/wiki/{repo}/{page}")  # noqa: SLF001

    def upload(self, ns: str, name: str) -> Response:
        """Add or replace a picture (or a .md page file) under wiki/."""
        repo, user, store, refused = self._open(ns, name, write=True)
        if refused is not None:
            return refused
        up = request.files.get("file")
        if up is None or not up.filename:
            return self._edit_form(repo, user, store, MAIN, "", status=HTTPStatus.BAD_REQUEST,
                                   error="файл не выбран")
        path = (request.form.get("page") or f"wiki/{up.filename}").strip()
        try:
            store.save(request.form.get("base", type=int, default=store.head()), {path: up.read()},
                       by=user, message=request.form.get("message", "") or f"файл {path}")
        except (WikiConflict, WikiRejected) as exc:
            return self._edit_form(repo, user, store, MAIN, "", status=HTTPStatus.BAD_REQUEST, error=str(exc))
        return self.server._redirect(f"/web/wiki/{repo}/{MAIN}")  # noqa: SLF001

    def delete(self, ns: str, name: str) -> Response:
        """Delete one page or picture (the main page goes only with the whole wiki)."""
        repo, user, store, refused = self._open(ns, name, write=True)
        if refused is not None:
            return refused
        page = request.form.get("page", "")
        try:
            store.save(request.form.get("base", type=int, default=0), {check_path(page): None},
                       by=user, message=f"удалено {page}")
        except (WikiConflict, WikiRejected) as exc:
            return self._edit_form(repo, user, store, MAIN, "", status=HTTPStatus.BAD_REQUEST, error=str(exc))
        return self.server._redirect(f"/web/wiki/{repo}/{MAIN}")  # noqa: SLF001

    def history(self, ns: str, name: str) -> Response:
        """Every version of the wiki: who, when, why, which pages."""
        repo, user, store, refused = self._open(ns, name)
        if refused is not None:
            return refused
        return self.server._html(_env.get_template("wiki_history.html.j2").render(  # noqa: SLF001
            title=f"История wiki {repo} — hashpass", versions=store.versions(), **self._ctx(repo, user, store)))

    def version(self, ns: str, name: str, n: int) -> Response:
        """Show what version `n` changed against `n - 1`."""
        repo, user, store, refused = self._open(ns, name)
        if refused is not None:
            return refused
        row = next((v for v in store.versions() if v["n"] == n), None)
        if row is None:
            return self.server._web_not_found(f"{repo} wiki {n}")  # noqa: SLF001
        return self.server._html(_env.get_template("wiki_history.html.j2").render(  # noqa: SLF001
            title=f"Wiki {repo}, версия {n} — hashpass", shown=row, files=store.diff(n - 1, n),
            versions=[], **self._ctx(repo, user, store)))
