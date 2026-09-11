"""
Pool registry HTTP server (Flask + werkzeug WSGI): image/task blobs + auth + roles + registration.

Binds a configurable host (default loopback). It holds the signing secret and the password
hashes, so every mutating or credit-granting request requires a valid bearer token, and role-gated
endpoints check the caller's role. It may be self-hosted as the pool; it must still NEVER be pointed
at or used to touch the legacy server (no 185.x).
"""
import contextlib
import json
import re
import socket
import tarfile
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, request
from werkzeug.serving import make_server as _wsgi_make_server

from hashpass.imagestore.store import ImageStore
from hashpass.key import global_key
from hashpass.registry.attachments import AttachmentStore, safe_filename
from hashpass.registry.blob import pack_image, pack_task, unpack_image, unpack_task
from hashpass.registry.catalog import Catalog
from hashpass.registry.config import ServerConfig, save_config
from hashpass.registry.passwords import ROLES, UserStore, WeakPasswordError, validate_password
from hashpass.registry.progress_store import ProgressStore
from hashpass.registry.refs import closure_refs
from hashpass.registry.token import issue_token, verify_token
from hashpass.registry.web import (
    render_catalog,
    render_dashboard,
    render_engine_install_script,
    render_front,
    render_history,
    render_image_card,
    render_install_script,
    render_login,
    render_password_form,
    render_reset_form,
    render_reset_link,
    render_users,
)
from hashpass.taskdigest import task_digest

_BEARER = "Bearer "
_MAX_BODY = 512 * 1024 * 1024  # cap request bodies to avoid memory blowup
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # safe as a login + a per-user progress filename
_AUTHOR_ROLES = ("author", "admin")
_MAX_COMMENT = 500
_MAX_ATTACH = 8 * 1024 * 1024   # per-file attachment cap (8 MiB)
_MAX_DESC = 2000                # image description cap
_MAX_HISTORY = 500              # command-history entries kept per submission
_MAX_CMD = 1000                 # per-command length kept
_AUTH_VERDICTS = ("typed", "pasted", "unknown")
_RESET_PREFIX = "reset:"                 # a reset token's subject; never a real login
_RESET_TTL = 2 * 24 * 60 * 60            # password-reset links live 2 days


def _now() -> str:
    """UTC timestamp (ISO-8601, second precision) for progress records."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    """
    Minimal multipart/form-data parser: return (text fields, file parts {name:(filename, bytes)}).

    Retained for the tier1 unit test that exercises it. Runtime uploads go through Flask's
    (werkzeug's) native multipart parser instead of this hand-rolled one.
    """
    match = re.search(r"boundary=([^;]+)", content_type)
    if not match:
        return {}, {}
    delim = b"--" + match.group(1).strip().strip('"').encode("utf-8", "replace")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for raw in body.split(delim):
        part = raw[2:] if raw.startswith(b"\r\n") else raw
        if part.endswith(b"\r\n"):
            part = part[:-2]
        head, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        head_s = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', head_s)
        if name is None:
            continue
        filename = re.search(r'filename="([^"]*)"', head_s)
        if filename is not None:
            files[name.group(1)] = (filename.group(1), content)
        else:
            fields[name.group(1)] = content.decode("utf-8", "replace")
    return fields, files


def _sanitize_history(raw: object) -> list[dict[str, object]] | None:
    """Coerce client-supplied command history into a safe, capped list (or None)."""
    if not isinstance(raw, list):
        return None
    out: list[dict[str, object]] = []
    for item in raw[:_MAX_HISTORY]:
        if not isinstance(item, dict):
            continue
        typing = item.get("typing")
        out.append({"command": str(item.get("command", ""))[:_MAX_CMD],
                    "ts": str(item.get("ts", ""))[:64],
                    "typing": float(typing) if isinstance(typing, (int, float)) else None,
                    "pasted": bool(item.get("pasted", False))})
    return out


def _sanitize_authenticity(raw: object) -> dict[str, object] | None:
    """Coerce the client-supplied anti-bot summary into a safe {verdict, typed, pasted} (or None)."""
    if not isinstance(raw, dict):
        return None
    verdict = str(raw.get("verdict", "unknown"))
    return {"verdict": verdict if verdict in _AUTH_VERDICTS else "unknown",
            "typed": int(raw["typed"]) if isinstance(raw.get("typed"), (int, float)) else 0,
            "pasted": int(raw["pasted"]) if isinstance(raw.get("pasted"), (int, float)) else 0}


class PoolServer:
    """Pool registry state (stores, secret, config) + a Flask WSGI app wired to it."""

    def __init__(self, *, store: ImageStore, users: UserStore, secret: bytes,   # noqa: PLR0913
                 config: ServerConfig | None = None,
                 config_path: Path | None = None, catalog_path: Path | None = None,
                 progress_path: Path | None = None, attachments_path: Path | None = None) -> None:
        """Wire stores + HMAC secret + on-disk paths into a Flask WSGI app built by `_build_app`."""
        self.store = store
        self.users = users
        self.secret = secret
        self.config = config or ServerConfig()
        self.config_path = config_path
        self.catalog_path = catalog_path
        self.progress_path = progress_path
        self.attachments_path = attachments_path
        self.app = self._build_app()

    def catalog(self) -> Catalog:
        return Catalog(self.catalog_path or (Path(self.store.root) / "catalog.json"))

    def progress(self) -> ProgressStore:
        return ProgressStore(self.progress_path or (Path(self.store.root) / "progress"))

    def attachments(self) -> AttachmentStore:
        return AttachmentStore(self.attachments_path or (Path(self.store.root) / "attachments"))

    # -- Flask app + route wiring --------------------------------------------

    def _build_app(self) -> Flask:
        here = Path(__file__).parent
        app = Flask("hashpass.registry",
                    static_folder=str(here / "static"),
                    static_url_path="/static")
        app.config["MAX_CONTENT_LENGTH"] = _MAX_BODY
        app.url_map.strict_slashes = False
        self._register_routes(app)
        return app

    def _register_routes(self, app: Flask) -> None:
        # public / installers
        app.add_url_rule("/", "root", self._route_front, methods=["GET"])
        app.add_url_rule("/install.sh", "install_sh", self._route_install_sh, methods=["GET"])
        app.add_url_rule("/install-engine.sh", "install_engine_sh",
                         self._route_install_engine_sh, methods=["GET"])
        # bearer-token endpoints for the student/author client
        app.add_url_rule("/login", "login", self._route_login, methods=["POST"])
        app.add_url_rule("/register", "register", self._route_register, methods=["POST"])
        app.add_url_rule("/admin/registration", "admin_registration",
                         self._route_admin_registration, methods=["POST"])
        app.add_url_rule("/admin/role", "admin_role", self._route_admin_role, methods=["POST"])
        app.add_url_rule("/submit", "submit", self._route_submit, methods=["POST"])
        app.add_url_rule("/me", "me", self._route_me, methods=["GET"])
        app.add_url_rule("/catalog", "catalog_api", self._route_catalog, methods=["GET"])
        app.add_url_rule("/progress", "progress_api", self._route_progress, methods=["GET"])
        app.add_url_rule("/images", "images_api", self._route_images, methods=["GET"])
        # blobs (name may be multi-segment; last segment is the version)
        app.add_url_rule("/image/<path:tail>", "image_blob", self._route_image_blob,
                         methods=["GET", "HEAD", "PUT"])
        app.add_url_rule("/task/<path:tail>", "task_blob", self._route_task_blob,
                         methods=["GET", "PUT"])
        app.add_url_rule("/closure/<path:tail>", "closure", self._route_closure, methods=["GET"])
        app.add_url_rule("/attachment/<path:tail>", "attachment_put",
                         self._route_attachment_put, methods=["PUT"])
        # web dashboard (cookie session)
        app.add_url_rule("/web", "web_dashboard", self._web_dashboard, methods=["GET"])
        app.add_url_rule("/web/login", "web_login_get", self._web_login_get, methods=["GET"])
        app.add_url_rule("/web/login", "web_login_post", self._web_login_post, methods=["POST"])
        app.add_url_rule("/web/logout", "web_logout", self._web_logout, methods=["GET"])
        app.add_url_rule("/web/users", "web_users", self._web_users, methods=["GET"])
        app.add_url_rule("/web/users/role", "web_users_role",
                         self._web_users_role, methods=["POST"])
        app.add_url_rule("/web/users/registration", "web_users_registration",
                         self._web_users_registration, methods=["POST"])
        app.add_url_rule("/web/users/reset", "web_users_reset",
                         self._web_users_reset_link, methods=["POST"])
        app.add_url_rule("/web/users/delete", "web_users_delete",
                         self._web_users_delete, methods=["POST"])
        app.add_url_rule("/web/users/delete-group", "web_users_delete_group",
                         self._web_users_delete_group, methods=["POST"])
        app.add_url_rule("/web/password", "web_password_get",
                         self._web_password_get, methods=["GET"])
        app.add_url_rule("/web/password", "web_password_post",
                         self._web_password_post, methods=["POST"])
        app.add_url_rule("/web/reset", "web_reset_get", self._web_reset_get, methods=["GET"])
        app.add_url_rule("/web/reset", "web_reset_post", self._web_reset_post, methods=["POST"])
        app.add_url_rule("/web/images", "web_images", self._web_images, methods=["GET"])
        app.add_url_rule("/web/image/<path:ref>", "web_image_card",
                         self._web_image_card, methods=["GET"])
        app.add_url_rule("/web/images/file", "web_image_file",
                         self._web_image_file, methods=["GET"])
        app.add_url_rule("/web/images/describe", "web_image_describe",
                         self._web_image_describe, methods=["POST"])
        app.add_url_rule("/web/images/attach", "web_image_attach",
                         self._web_image_attach, methods=["POST"])
        app.add_url_rule("/web/images/attach-delete", "web_image_attach_delete",
                         self._web_image_attach_delete, methods=["POST"])
        app.add_url_rule("/web/history", "web_history", self._web_history, methods=["GET"])
        app.add_url_rule("/web/catalog/add", "web_catalog_add",
                         self._web_catalog_add, methods=["POST"])
        app.add_url_rule("/web/catalog/remove", "web_catalog_remove",
                         self._web_catalog_remove, methods=["POST"])
        app.add_url_rule("/web/catalog/layout", "web_catalog_layout",
                         self._web_catalog_layout, methods=["POST"])
        app.add_url_rule("/web/tasks/toggle", "web_task_toggle",
                         self._web_task_toggle, methods=["POST"])
        app.add_url_rule("/web/blocks/add", "web_block_add",
                         self._web_block_add, methods=["POST"])
        app.add_url_rule("/web/blocks/rename", "web_block_rename",
                         self._web_block_rename, methods=["POST"])
        app.add_url_rule("/web/blocks/remove", "web_block_remove",
                         self._web_block_remove, methods=["POST"])
        app.add_url_rule("/web/blocks/toggle", "web_block_toggle",
                         self._web_block_toggle, methods=["POST"])

    # -- response helpers ---------------------------------------------------

    @staticmethod
    def _empty(status: HTTPStatus) -> Response:
        resp = Response(b"", status=int(status))
        resp.headers["Content-Length"] = "0"
        return resp

    @staticmethod
    def _json(status: HTTPStatus, payload: dict) -> Response:
        return Response(json.dumps(payload), status=int(status), mimetype="application/json")

    @staticmethod
    def _blob(status: HTTPStatus, blob: bytes) -> Response:
        return Response(blob, status=int(status), mimetype="application/octet-stream")

    @staticmethod
    def _html(body: str, status: HTTPStatus = HTTPStatus.OK) -> Response:
        return Response(body, status=int(status), mimetype="text/html; charset=utf-8")

    @staticmethod
    def _serve_script(body: str) -> Response:
        return Response(body, status=200, mimetype="text/x-shellscript; charset=utf-8")

    @staticmethod
    def _redirect(location: str, *, clear_cookie: bool = False,
                  set_cookie: tuple[str, str] | None = None) -> Response:
        resp = Response(b"", status=int(HTTPStatus.SEE_OTHER))
        resp.headers["Location"] = location
        resp.autocorrect_location_header = False   # keep the raw path (tests check the exact string)
        resp.headers["Content-Length"] = "0"
        if clear_cookie:
            resp.set_cookie("hp_session", "", max_age=0, path="/")
        if set_cookie is not None:
            name, value = set_cookie
            resp.set_cookie(name, value, path="/", httponly=True, samesite="Lax")
        return resp

    # -- auth helpers -------------------------------------------------------

    def _token_user(self) -> str | None:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith(_BEARER):
            return None
        return verify_token(self.secret, auth[len(_BEARER):], now=time.time())

    def _auth_role(self, roles: tuple[str, ...]) -> tuple[str | None, HTTPStatus | None]:
        """Return (user, None) if the bearer token maps to a user in `roles`, else (None, 401/403)."""
        user = self._token_user()
        if user is None:
            return None, HTTPStatus.UNAUTHORIZED
        if self.users.role(user) not in roles:
            return None, HTTPStatus.FORBIDDEN
        return user, None

    def _session_user(self) -> str | None:
        token = request.cookies.get("hp_session")
        if not token:
            return None
        return verify_token(self.secret, token, now=time.time())

    def _session_role(self, roles: tuple[str, ...]) -> str | None:
        user = self._session_user()
        if user is not None and self.users.role(user) in roles:
            return user
        return None

    def _pool_url(self) -> str:
        return f"{request.scheme}://{request.host}"

    @staticmethod
    def _split_ref(tail: str) -> tuple[str, str] | None:
        """`ns/name/version` -> ('ns/name', 'version'); at least one name segment required."""
        if "/" not in tail:
            return None
        name, version = tail.rsplit("/", 1)
        if not name or not version:
            return None
        return name, version

    # -- routes: public / installers ----------------------------------------

    def _route_front(self) -> Response:
        return self._html(render_front(self._pool_url()))

    def _route_install_sh(self) -> Response:
        return self._serve_script(render_install_script(self._pool_url()))

    def _route_install_engine_sh(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        return self._serve_script(render_engine_install_script(self._pool_url()))

    # -- routes: API auth --------------------------------------------------

    def _route_login(self) -> Response:
        creds = request.get_json(silent=True) or {}
        if not isinstance(creds, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        user = str(creds.get("user", ""))
        if not self.users.verify(user, str(creds.get("password", ""))):
            return self._empty(HTTPStatus.UNAUTHORIZED)
        return self._json(HTTPStatus.OK,
                          {"token": issue_token(self.secret, user, now=time.time())})

    def _route_register(self) -> Response:
        if not self.config.registration_open:
            return self._empty(HTTPStatus.FORBIDDEN)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        user = str(data.get("user", "")).strip()
        password = str(data.get("password", ""))
        group = str(data.get("group", "")).strip()
        comment = str(data.get("comment", "")).strip()[:_MAX_COMMENT]
        if not _USER_RE.match(user) or not password or not group:
            return self._empty(HTTPStatus.BAD_REQUEST)
        try:
            validate_password(password)
        except WeakPasswordError as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        if self.users.has(user):
            return self._empty(HTTPStatus.CONFLICT)
        self.users.add(user, password, role="student", group=group, comment=comment)
        return self._json(HTTPStatus.CREATED,
                          {"token": issue_token(self.secret, user, now=time.time())})

    def _route_admin_registration(self) -> Response:
        _user, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        self.config.registration_open = bool(data.get("open", True))
        if self.config_path is not None:
            save_config(self.config_path, self.config)
        return self._json(HTTPStatus.OK,
                          {"registration_open": self.config.registration_open})

    def _route_admin_role(self) -> Response:
        actor, err = self._auth_role(("admin",))
        if err is not None:
            return self._empty(err)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        target = str(data.get("user", ""))
        role = str(data.get("role", ""))
        if role not in ROLES:
            return self._empty(HTTPStatus.BAD_REQUEST)
        if target == actor:                          # an admin cannot change their own role
            return self._empty(HTTPStatus.FORBIDDEN)
        try:
            self.users.set_role(target, role)
        except KeyError:
            return self._empty(HTTPStatus.NOT_FOUND)
        return self._json(HTTPStatus.OK, {"user": target, "role": role})

    def _route_me(self) -> Response:
        user = self._token_user()
        profile = self.users.get(user) if user is not None else None
        if profile is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        return self._json(HTTPStatus.OK, profile)

    def _route_catalog(self) -> Response:
        if self._token_user() is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        return self._json(HTTPStatus.OK,
                          {"catalog": [e.as_dict() for e in self.catalog().entries()]})

    def _route_submit(self) -> Response:   # noqa: PLR0911
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return self._empty(HTTPStatus.BAD_REQUEST)
        task_ref = str(data.get("task_ref", ""))
        digest = str(data.get("digest", ""))
        passed = bool(data.get("passed", False))
        history = _sanitize_history(data.get("history"))
        authenticity = _sanitize_authenticity(data.get("authenticity"))
        entry = self.catalog().find(task_ref)
        if entry is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        if not entry.available:
            return self._json(HTTPStatus.OK, {"status": "unavailable"})
        prog = self.progress()
        if digest != entry.digest:
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest,
                        history=history, authenticity=authenticity)
            return self._json(HTTPStatus.OK, {"status": "failed", "reason": "digest-mismatch"})
        if not passed:
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest,
                        history=history, authenticity=authenticity)
            return self._json(HTTPStatus.OK, {"status": "failed"})
        gkey = global_key(self.secret, user, task_ref)   # bound to the authenticated principal
        prog.record(user, task_ref, status="passed", ts=_now(), global_key=gkey, digest=digest,
                    history=history, authenticity=authenticity)
        return self._json(HTTPStatus.OK, {"status": "passed", "global_key": gkey})

    def _route_progress(self) -> Response:
        user = self._token_user()
        if user is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        store = self.progress()
        payload = store.all() if self.users.role(user) in _AUTHOR_ROLES else {user: store.get(user)}
        return self._json(HTTPStatus.OK, {"progress": payload})

    def _pool_image_rows(self) -> list[dict[str, object]]:
        entries = {e.ref: e for e in self.catalog().entries()}
        att = self.attachments()
        rows: list[dict[str, object]] = []
        for ref in self.store.list():
            is_task = (self.store.get(ref).layer.parent / "task").exists()
            entry = entries.get(ref)
            info = att.describe(ref)
            rows.append({"ref": ref, "kind": "task" if is_task else "image",
                         "number": entry.number if entry else None,
                         "block_id": entry.block_id if entry else None,
                         "block_name": entry.block_name if entry else "",
                         "available": entry.available if entry else None,
                         "description": info["description"], "files": info["files"]})
        return rows

    def _route_images(self) -> Response:
        if self._token_user() is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        return self._json(HTTPStatus.OK, {"images": self._pool_image_rows()})

    # -- routes: blobs (image / task / closure / attachment) ----------------

    def _route_image_blob(self, tail: str) -> Response:   # noqa: PLR0911
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        ref = f"{name}:{version}"
        if request.method == "HEAD":
            return self._empty(HTTPStatus.OK if self.store.exists(ref) else HTTPStatus.NOT_FOUND)
        if request.method == "PUT":
            _user, err = self._auth_role(("author", "admin"))
            if err is not None:
                return self._empty(err)
            try:
                unpack_image(request.get_data(cache=False, as_text=False), self.store)
            except (ValueError, KeyError, OSError, tarfile.TarError):
                return self._empty(HTTPStatus.BAD_REQUEST)
            return self._empty(HTTPStatus.CREATED)
        # GET
        try:
            img = self.store.get(ref)
        except KeyError:
            return self._empty(HTTPStatus.NOT_FOUND)
        return self._blob(HTTPStatus.OK, pack_image(img))

    def _route_task_blob(self, tail: str) -> Response:   # noqa: PLR0911
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        ref = f"{name}:{version}"
        if request.method == "PUT":
            _user, err = self._auth_role(("author", "admin"))
            if err is not None:
                return self._empty(err)
            if not self.store.exists(ref):
                return self._empty(HTTPStatus.NOT_FOUND)
            task_dir = self.store.get(ref).layer.parent / "task"
            try:
                unpack_task(request.get_data(cache=False, as_text=False), task_dir)
            except (ValueError, OSError, tarfile.TarError):
                return self._empty(HTTPStatus.BAD_REQUEST)
            if request.args.get("publish", "") == "1":   # `push --task`: add to the catalog (auto-№)
                self.catalog().add_task(ref, task_digest(task_dir))
            return self._empty(HTTPStatus.CREATED)
        # GET (a task's grader is not public)
        if self._token_user() is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        if not self.store.exists(ref):
            return self._empty(HTTPStatus.NOT_FOUND)
        task_dir = self.store.get(ref).layer.parent / "task"
        if not task_dir.exists():
            return self._empty(HTTPStatus.NOT_FOUND)
        return self._blob(HTTPStatus.OK, pack_task(task_dir))

    def _route_closure(self, tail: str) -> Response:
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        try:
            refs = closure_refs(f"{name}:{version}", self.store)
        except KeyError:
            return self._empty(HTTPStatus.NOT_FOUND)
        return self._json(HTTPStatus.OK, {"refs": refs})

    def _route_attachment_put(self, tail: str) -> Response:
        parts = self._split_ref(tail)
        if parts is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        name, version = parts
        ref = f"{name}:{version}"
        _user, err = self._auth_role(_AUTHOR_ROLES)
        if err is not None:
            return self._empty(err)
        if not self.store.exists(ref):
            return self._empty(HTTPStatus.NOT_FOUND)
        filename = request.args.get("name", "")
        body = request.get_data(cache=False, as_text=False)
        if not filename or not body or len(body) > _MAX_ATTACH:
            return self._empty(HTTPStatus.BAD_REQUEST)
        taskfile = request.args.get("taskfile", "") == "1"
        try:
            self.attachments().put_file(ref, filename, body, taskfile=taskfile)
        except (ValueError, OSError):
            return self._empty(HTTPStatus.BAD_REQUEST)
        return self._empty(HTTPStatus.CREATED)

    # -- routes: web dashboard ---------------------------------------------

    def _web_dashboard(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        group = request.args.get("group") or None
        return self._html(render_dashboard(
            self.users.all_users(),
            [e.as_dict() for e in self.catalog().entries()],
            self.progress().all(), group=group))

    def _web_users(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        return self._html(render_users(
            self.users.all_users(),
            registration_open=self.config.registration_open, current_user=actor))

    def _web_images(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        blocks = [b.as_dict() for b in self.catalog().blocks()]
        return self._html(render_catalog(self._pool_image_rows(), blocks))

    def _web_image_card(self, ref: str) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        if not self.store.exists(ref):
            return self._empty(HTTPStatus.NOT_FOUND)
        row = next((r for r in self._pool_image_rows() if r["ref"] == ref), None)
        if row is None:
            return self._empty(HTTPStatus.NOT_FOUND)
        entry = self.catalog().find(ref)
        row = {**row, "hidden": entry.hidden if entry else False}
        return self._html(render_image_card(row))

    def _web_history(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        user, ref = request.args.get("user", ""), request.args.get("ref", "")
        record = self.progress().get(user).get(ref, {}) if user else {}
        return self._html(render_history(user, ref, record))

    def _web_login_get(self) -> Response:
        return self._html(render_login())

    def _web_login_post(self) -> Response:
        user = request.form.get("user", "").strip()
        if (self.users.verify(user, request.form.get("password", ""))
                and self.users.role(user) in _AUTHOR_ROLES):
            token = issue_token(self.secret, user, now=time.time())
            return self._redirect("/web", set_cookie=("hp_session", token))
        return self._html(render_login("Неверный логин/пароль или нет доступа."),
                          status=HTTPStatus.UNAUTHORIZED)

    def _web_logout(self) -> Response:
        return self._redirect("/web/login", clear_cookie=True)

    def _web_password_get(self) -> Response:
        if self._session_user() is None:
            return self._redirect("/web/login")
        return self._html(render_password_form())

    def _web_password_post(self) -> Response:
        user = self._session_user()
        if user is None:
            return self._redirect("/web/login")
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        if not new or new != confirm:
            return self._html(render_password_form("новые пароли пусты или не совпадают"))
        if not self.users.verify(user, request.form.get("old", "")):
            return self._html(render_password_form("неверный текущий пароль"))
        try:
            validate_password(new)
        except WeakPasswordError as exc:
            return self._html(render_password_form(str(exc)))
        self.users.set_password(user, new)
        return self._html(render_password_form(done=True))

    def _web_reset_get(self) -> Response:
        token = request.args.get("token", "")
        return self._html(render_reset_form(token))

    def _web_reset_post(self) -> Response:
        token = request.form.get("token", "")
        subject = verify_token(self.secret, token, now=time.time())
        if subject is None or not subject.startswith(_RESET_PREFIX):
            return self._html(render_reset_form(token, "ссылка недействительна или истекла"))
        new, confirm = request.form.get("new", ""), request.form.get("confirm", "")
        if not new or new != confirm:
            return self._html(render_reset_form(token, "пароли пусты или не совпадают"))
        try:
            validate_password(new)
        except WeakPasswordError as exc:
            return self._html(render_reset_form(token, str(exc)))
        try:
            self.users.set_password(subject[len(_RESET_PREFIX):], new)
        except KeyError:
            return self._html(render_reset_form(token, "пользователь не найден"))
        return self._redirect("/web/login")

    def _web_users_role(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "").strip()
        role = request.form.get("role", "")
        if target != actor and role in ROLES and self.users.has(target):
            self.users.set_role(target, role)   # never change your own role (self-lockout)
        return self._redirect("/web/users")

    def _web_users_registration(self) -> Response:
        if self._session_role(("admin",)) is None:
            return self._redirect("/web/login")
        self.config.registration_open = request.form.get("open") == "true"
        if self.config_path is not None:
            save_config(self.config_path, self.config)
        return self._redirect("/web/users")

    def _web_users_reset_link(self) -> Response:
        if self._session_role(("admin",)) is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "")
        if not self.users.has(target):
            return self._redirect("/web/users")
        token = issue_token(self.secret, _RESET_PREFIX + target,
                            now=time.time(), ttl=_RESET_TTL)
        return self._html(
            render_reset_link(target, f"{self._pool_url()}/web/reset?token={token}"))

    def _web_users_delete(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        target = request.form.get("user", "").strip()
        if target and target != actor:                 # never delete yourself
            self.users.delete(target)
            self.progress().delete(target)
        return self._redirect("/web/users")

    def _web_users_delete_group(self) -> Response:
        actor = self._session_role(("admin",))
        if actor is None:
            return self._redirect("/web/login")
        group = request.form.get("group", "").strip()
        if group:
            prog = self.progress()
            for profile in self.users.all_users():
                user = str(profile["user"])
                if str(profile.get("group", "")) == group and user != actor:
                    self.users.delete(user)
                    prog.delete(user)
        return self._redirect("/web/users")

    def _web_ref_form(self) -> tuple[str, str] | None:
        """Author-gate a POST, return (ref, form-ref) if the ref exists, else redirect (returns None)."""
        if self._session_role(_AUTHOR_ROLES) is None:
            return None
        ref = request.form.get("ref", "")
        if not ref or not self.store.exists(ref):
            return None
        return ref, ref

    @staticmethod
    def _card_url(ref: str) -> str:
        """Path to the image card page for one ref (URL-encoded, matches the /web/image/<ref> route)."""
        return f"/web/image/{quote(ref, safe='/:')}" if ref else "/web/images"

    def _web_image_describe(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref = request.form.get("ref", "")
        if not ref or not self.store.exists(ref):
            return self._redirect("/web/images")
        with contextlib.suppress(ValueError, OSError):
            self.attachments().set_description(ref, request.form.get("description", "")[:_MAX_DESC])
        return self._redirect(self._card_url(ref))

    def _web_image_attach(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref = request.form.get("ref", "")
        upload = request.files.get("file")
        if ref and self.store.exists(ref) and upload and upload.filename:
            data = upload.read()
            if data and len(data) <= _MAX_ATTACH:
                with contextlib.suppress(ValueError, OSError):
                    self.attachments().put_file(ref, upload.filename, data)
        return self._redirect(self._card_url(ref))

    def _web_image_attach_delete(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref = request.form.get("ref", "")
        if not ref or not self.store.exists(ref):
            return self._redirect("/web/images")
        with contextlib.suppress(ValueError, OSError):
            self.attachments().delete_file(ref, request.form.get("name", ""))
        return self._redirect(self._card_url(ref))

    def _web_image_file(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref, name = request.args.get("ref", ""), request.args.get("name", "")
        try:
            blob = self.attachments().read_file(ref, name)
            safe = safe_filename(name)
        except (ValueError, FileNotFoundError, OSError):
            return self._empty(HTTPStatus.NOT_FOUND)
        resp = Response(blob, status=200, mimetype="application/octet-stream")
        resp.headers["Content-Disposition"] = f'attachment; filename="{safe}"'
        return resp

    def _web_catalog_add(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref = request.form.get("ref", "")
        if not ref or not self.store.exists(ref):
            return self._redirect("/web/images")
        task_dir = self.store.get(ref).layer.parent / "task"
        if not task_dir.exists():   # only a task image (with a grader) can join the catalog
            return self._redirect("/web/images")
        self.catalog().add_task(ref, task_digest(task_dir),
                                block_id=request.form.get("block_id") or None)
        return self._redirect("/web/images")

    def _web_catalog_remove(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref = request.form.get("ref", "")
        if not ref or not self.store.exists(ref):
            return self._redirect("/web/images")
        self.catalog().remove_task(ref)
        return self._redirect("/web/images")

    def _web_task_toggle(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        ref = request.form.get("ref", "")
        if not ref:
            return self._redirect("/web/images")
        self.catalog().set_task_hidden(ref, hidden=request.form.get("hidden", "") == "1")
        return self._redirect("/web/images")

    def _web_catalog_layout(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._empty(HTTPStatus.UNAUTHORIZED)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
            return self._empty(HTTPStatus.BAD_REQUEST)
        self.catalog().set_layout(data["blocks"])
        return self._json(HTTPStatus.OK, {"ok": True})

    def _web_block_add(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().add_block(request.form.get("name", "").strip() or "Блок")
        return self._redirect("/web/images")

    def _web_block_rename(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().rename_block(request.form.get("block_id", ""),
                                    request.form.get("name", "").strip() or "Блок")
        return self._redirect("/web/images")

    def _web_block_remove(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().remove_block(request.form.get("block_id", ""))
        return self._redirect("/web/images")

    def _web_block_toggle(self) -> Response:
        if self._session_role(_AUTHOR_ROLES) is None:
            return self._redirect("/web/login")
        self.catalog().set_block_open(request.form.get("block_id", ""),
                                      open_=request.form.get("open", "") == "1")
        return self._redirect("/web/images")


def make_server(store: ImageStore, users: UserStore, secret: bytes, *,   # noqa: PLR0913
                host: str = "127.0.0.1", port: int = 0,
                config: ServerConfig | None = None,
                config_path: Path | None = None,
                catalog_path: Path | None = None,
                progress_path: Path | None = None, attachments_path: Path | None = None,
                certfile: Path | None = None, keyfile: Path | None = None):
    """
    Create a pool registry server (port 0 = ephemeral). Default host is loopback.

    Returns a werkzeug WSGI server (`serve_forever` / `shutdown` / `server_address` /
    `server_close`), backing the same Flask app. With `certfile`+`keyfile`, the listener
    is TLS-wrapped (HTTPS) via stdlib `ssl` — same behavior as the previous stdlib server.
    """
    pool = PoolServer(store=store, users=users, secret=secret, config=config,
                      config_path=config_path, catalog_path=catalog_path,
                      progress_path=progress_path, attachments_path=attachments_path)
    ssl_context = (str(certfile), str(keyfile)) if certfile is not None and keyfile is not None else None
    if port != 0:
        # Werkzeug's make_server sys.exit(1)s on bind failure; do a preflight bind so a busy port
        # surfaces to callers as OSError (the previous stdlib server behaved this way, and tests
        # rely on it -- e.g. the admin seed must be skipped when the pool can't bind).
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
    server = _wsgi_make_server(host, port, pool.app, threaded=True, ssl_context=ssl_context)
    server.pool = pool         # let callers/tests reach the state directly (matches the old attrs)
    return server
