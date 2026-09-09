"""
Pool registry HTTP server (stdlib http.server): image/task blobs + auth + roles + registration.

Binds a configurable host (default loopback). It holds the signing secret and the password
hashes, so every mutating or credit-granting request requires a valid bearer token, and role-gated
endpoints check the caller's role. It may be self-hosted as the pool; it must still NEVER be pointed
at or used to touch the legacy server (no 185.x).
"""
import contextlib
import json
import re
import ssl
import tarfile
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
    render_dashboard,
    render_engine_install_script,
    render_front,
    render_history,
    render_images,
    render_install_script,
    render_login,
    render_password_form,
    render_reset_form,
    render_reset_link,
    render_users,
)
from hashpass.taskdigest import task_digest

_BEARER = "Bearer "
_MIN_IMAGE_PARTS = 3  # /<kind>/<name.../>/<version>: kind + >=1 name segment + version
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

    Enough for one small upload form; binary file content is preserved exactly (only the
    structural CRLFs around each part are stripped, never bytes inside the content).
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


class RegistryServer(ThreadingHTTPServer):
    """A pool registry server holding the HMAC secret, user store, and runtime config."""

    daemon_threads = True         # worker threads never block process exit (clean Ctrl-C)
    allow_reuse_address = True    # rebind the port immediately after a restart

    def __init__(self, address: tuple[str, int], *, store: ImageStore,  # noqa: PLR0913
                 users: UserStore, secret: bytes, config: ServerConfig | None = None,
                 config_path: Path | None = None, catalog_path: Path | None = None,
                 progress_path: Path | None = None, attachments_path: Path | None = None) -> None:
        """Bind the server with its stores, HMAC secret, config, catalog, and progress dir."""
        super().__init__(address, _Handler)
        self.store = store
        self.users = users
        self.secret = secret
        self.config = config or ServerConfig()
        self.config_path = config_path
        self.catalog_path = catalog_path
        self.progress_path = progress_path
        self.attachments_path = attachments_path

    def catalog(self) -> Catalog:
        """Return a Catalog over this server's catalog file (next to the store if none was set)."""
        return Catalog(self.catalog_path or (Path(self.store.root) / "catalog.json"))

    def progress(self) -> ProgressStore:
        """Return a ProgressStore over this server's progress dir (next to the store by default)."""
        return ProgressStore(self.progress_path or (Path(self.store.root) / "progress"))

    def attachments(self) -> AttachmentStore:
        """Return an AttachmentStore over this server's attachments dir (next to the store)."""
        return AttachmentStore(self.attachments_path or (Path(self.store.root) / "attachments"))


class _Handler(BaseHTTPRequestHandler):
    """Pool routes: auth, image/task/closure blobs, catalog/submit/progress, and the /web dashboard."""

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence per-request stderr logging."""

    def _empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _blob(self, status: HTTPStatus, blob: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return b""  # malformed header -> empty body -> caller returns 400
        if length <= 0 or length > _MAX_BODY:
            return b""  # absent/oversized -> don't buffer a huge/garbage body; caller 400s
        return self.rfile.read(length)

    def _json_body(self) -> dict[str, object] | None:
        try:
            data = json.loads(self._read_body().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _token_user(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith(_BEARER):
            return None
        return verify_token(self.server.secret, auth[len(_BEARER):], now=time.time())

    def _auth_role(self, roles: tuple[str, ...]) -> tuple[str | None, HTTPStatus | None]:
        """Return (user, None) if the bearer token maps to a user in `roles`, else (None, 401/403)."""
        user = self._token_user()
        if user is None:
            return None, HTTPStatus.UNAUTHORIZED
        if self.server.users.role(user) not in roles:
            return None, HTTPStatus.FORBIDDEN
        return user, None

    def _parts_for(self, kind: str) -> tuple[str, str] | None:
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) >= _MIN_IMAGE_PARTS and parts[0] == kind:
            # /<kind>/<name.../>/<version>: name may be multi-segment (`ns/app`), version is last.
            return "/".join(parts[1:-1]), parts[-1]
        return None

    def _image_parts(self) -> tuple[str, str] | None:
        return self._parts_for("image")

    # -- POST --------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: C901, PLR0912  (a flat route dispatcher)
        path = urlsplit(self.path).path
        if path == "/login":
            self._login()
        elif path == "/register":
            self._register()
        elif path == "/admin/registration":
            self._admin_registration()
        elif path == "/admin/role":
            self._admin_role()
        elif path == "/submit":
            self._submit()
        elif path == "/web/login":
            self._web_login()
        elif path == "/web/users/role":
            self._web_set_role()
        elif path == "/web/users/registration":
            self._web_registration()
        elif path == "/web/password":
            self._web_password_change()
        elif path == "/web/reset":
            self._web_reset_do()
        elif path == "/web/users/reset":
            self._web_reset_link()
        elif path == "/web/users/delete":
            self._web_delete_user()
        elif path == "/web/users/delete-group":
            self._web_delete_group()
        elif path == "/web/images/describe":
            self._web_image_describe()
        elif path == "/web/images/attach":
            self._web_image_attach()
        elif path == "/web/images/attach-delete":
            self._web_image_attach_delete()
        elif path == "/web/catalog/add":
            self._web_catalog_add()
        elif path == "/web/catalog/remove":
            self._web_catalog_remove()
        elif path == "/web/catalog/layout":
            self._web_catalog_layout()
        elif path == "/web/blocks/add":
            self._web_block_add()
        elif path == "/web/blocks/rename":
            self._web_block_rename()
        elif path == "/web/blocks/remove":
            self._web_block_remove()
        elif path == "/web/blocks/toggle":
            self._web_block_toggle()
        else:
            self._empty(HTTPStatus.NOT_FOUND)

    def _login(self) -> None:
        creds = self._json_body()
        if creds is None:
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        user = str(creds.get("user", ""))
        if not self.server.users.verify(user, str(creds.get("password", ""))):
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        self._json(HTTPStatus.OK, {"token": issue_token(self.server.secret, user, now=time.time())})

    def _register(self) -> None:
        if not self.server.config.registration_open:
            self._empty(HTTPStatus.FORBIDDEN)
            return
        data = self._json_body()
        if data is None:
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        user = str(data.get("user", "")).strip()
        password = str(data.get("password", ""))
        group = str(data.get("group", "")).strip()
        comment = str(data.get("comment", "")).strip()[:_MAX_COMMENT]
        if not _USER_RE.match(user) or not password or not group:
            self._empty(HTTPStatus.BAD_REQUEST)  # safe login + password + group are mandatory
            return
        try:
            validate_password(password)
        except WeakPasswordError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if self.server.users.has(user):
            self._empty(HTTPStatus.CONFLICT)
            return
        self.server.users.add(user, password, role="student", group=group, comment=comment)
        self._json(HTTPStatus.CREATED,
                   {"token": issue_token(self.server.secret, user, now=time.time())})

    def _admin_registration(self) -> None:
        _user, err = self._auth_role(("admin",))
        if err is not None:
            self._empty(err)
            return
        data = self._json_body()
        if data is None:
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        self.server.config.registration_open = bool(data.get("open", True))
        if self.server.config_path is not None:
            save_config(self.server.config_path, self.server.config)
        self._json(HTTPStatus.OK, {"registration_open": self.server.config.registration_open})

    def _admin_role(self) -> None:
        _user, err = self._auth_role(("admin",))
        if err is not None:
            self._empty(err)
            return
        data = self._json_body()
        if data is None:
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        target = str(data.get("user", ""))
        role = str(data.get("role", ""))
        if role not in ROLES:
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        if target == _user:                          # an admin cannot change their own role
            self._empty(HTTPStatus.FORBIDDEN)
            return
        try:
            self.server.users.set_role(target, role)
        except KeyError:
            self._empty(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"user": target, "role": role})

    # -- GET / HEAD / PUT --------------------------------------------------

    def do_GET(self) -> None:  # noqa: PLR0911, C901  (a flat route dispatcher)
        path = urlsplit(self.path).path
        if path == "/" or path.startswith("/web"):
            self._web_get(path)
            return
        if path == "/install.sh":
            self._serve_script(render_install_script(self._pool_url()))
            return
        if path == "/install-engine.sh":
            if self._session_role(_AUTHOR_ROLES) is None:
                self._redirect("/web/login")   # engine install is author-gated on the site
                return
            self._serve_script(render_engine_install_script(self._pool_url()))
            return
        if path == "/me":
            self._me()
            return
        if path == "/catalog":
            self._catalog()
            return
        if path == "/progress":
            self._progress()
            return
        if path == "/images":
            self._images()
            return
        parts = path.strip("/").split("/")
        if len(parts) >= _MIN_IMAGE_PARTS and parts[0] == "closure":
            self._serve_closure(f"{'/'.join(parts[1:-1])}:{parts[-1]}")
        elif (target := self._image_parts()) is not None:
            self._serve_image(f"{target[0]}:{target[1]}")
        elif (task := self._parts_for("task")) is not None:
            self._serve_task(f"{task[0]}:{task[1]}")
        else:
            self._empty(HTTPStatus.NOT_FOUND)

    def _me(self) -> None:
        user = self._token_user()
        profile = self.server.users.get(user) if user is not None else None
        if profile is None:
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        self._json(HTTPStatus.OK, profile)

    def _catalog(self) -> None:
        if self._token_user() is None:
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        # Students see every task (each carries `available`); a closed one is shown but locked
        # -- it is not pulled and its /submit is refused below.
        self._json(HTTPStatus.OK,
                   {"catalog": [e.as_dict() for e in self.server.catalog().entries()]})

    def _submit(self) -> None:
        user = self._token_user()
        if user is None:
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        data = self._json_body()
        if data is None:
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        task_ref = str(data.get("task_ref", ""))
        digest = str(data.get("digest", ""))
        passed = bool(data.get("passed", False))
        history = _sanitize_history(data.get("history"))       # client-supplied -> sanitize
        authenticity = _sanitize_authenticity(data.get("authenticity"))
        entry = self.server.catalog().find(task_ref)
        if entry is None:
            self._empty(HTTPStatus.NOT_FOUND)
            return
        if not entry.available:   # a hidden task accepts no submissions (no credit while closed)
            self._json(HTTPStatus.OK, {"status": "unavailable"})
            return
        prog = self.server.progress()
        if digest != entry.digest:  # the task was altered locally -> no credit (basic integrity)
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest,
                        history=history, authenticity=authenticity)
            self._json(HTTPStatus.OK, {"status": "failed", "reason": "digest-mismatch"})
            return
        if not passed:
            prog.record(user, task_ref, status="failed", ts=_now(), digest=digest,
                        history=history, authenticity=authenticity)
            self._json(HTTPStatus.OK, {"status": "failed"})
            return
        gkey = global_key(self.server.secret, user, task_ref)  # bound to the authenticated principal
        prog.record(user, task_ref, status="passed", ts=_now(), global_key=gkey, digest=digest,
                    history=history, authenticity=authenticity)
        self._json(HTTPStatus.OK, {"status": "passed", "global_key": gkey})

    def _progress(self) -> None:
        user = self._token_user()
        if user is None:
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        store = self.server.progress()
        payload = store.all() if self.server.users.role(user) in _AUTHOR_ROLES else {user: store.get(user)}
        self._json(HTTPStatus.OK, {"progress": payload})

    def _pool_image_rows(self) -> list[dict[str, object]]:
        entries = {e.ref: e for e in self.server.catalog().entries()}
        att = self.server.attachments()
        rows: list[dict[str, object]] = []
        for ref in self.server.store.list():
            is_task = (self.server.store.get(ref).layer.parent / "task").exists()
            entry = entries.get(ref)
            info = att.describe(ref)
            rows.append({"ref": ref, "kind": "task" if is_task else "image",
                         "number": entry.number if entry else None,
                         "block_id": entry.block_id if entry else None,
                         "block_name": entry.block_name if entry else "",
                         "available": entry.available if entry else None,
                         "description": info["description"], "files": info["files"]})
        return rows

    def _images(self) -> None:
        if self._token_user() is None:
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        self._json(HTTPStatus.OK, {"images": self._pool_image_rows()})

    # -- web dashboard (server-rendered HTML, cookie session) --------------

    def _html(self, status: HTTPStatus, body: str, *, cookie: str | None = None) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _serve_script(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/x-shellscript; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str, *, cookie: str | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _pool_url(self) -> str:
        scheme = "https" if isinstance(self.connection, ssl.SSLSocket) else "http"
        return f"{scheme}://{self.headers.get('Host', '127.0.0.1')}"

    def _form(self) -> dict[str, str]:
        parsed = parse_qs(self._read_body().decode("utf-8", "replace"))
        return {key: values[0] for key, values in parsed.items()}

    def _session_user(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        jar = SimpleCookie()
        jar.load(raw)
        if "hp_session" not in jar:
            return None
        return verify_token(self.server.secret, jar["hp_session"].value, now=time.time())

    def _session_role(self, roles: tuple[str, ...]) -> str | None:
        user = self._session_user()
        if user is not None and self.server.users.role(user) in roles:
            return user
        return None

    def _web_get(self, path: str) -> None:  # noqa: C901  (a flat route dispatcher)
        if path == "/":
            self._html(HTTPStatus.OK, render_front(self._pool_url()))
        elif path == "/web/login":
            self._html(HTTPStatus.OK, render_login())
        elif path == "/web/logout":
            self._redirect("/web/login", cookie="hp_session=; Max-Age=0; Path=/")
        elif path == "/web":
            self._web_dashboard()
        elif path == "/web/users":
            self._web_users()
        elif path == "/web/images":
            self._web_images()
        elif path == "/web/images/file":
            self._web_attachment_download()
        elif path == "/web/history":
            self._web_history()
        elif path == "/web/password":
            self._web_password_form()
        elif path == "/web/reset":
            token = parse_qs(urlsplit(self.path).query).get("token", [""])[0]
            self._html(HTTPStatus.OK, render_reset_form(token))
        else:
            self._empty(HTTPStatus.NOT_FOUND)

    def _web_dashboard(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        group = parse_qs(urlsplit(self.path).query).get("group", [None])[0]
        self._html(HTTPStatus.OK, render_dashboard(
            self.server.users.all_users(),
            [e.as_dict() for e in self.server.catalog().entries()],
            self.server.progress().all(), group=group))

    def _web_users(self) -> None:
        actor = self._session_role(("admin",))
        if actor is None:
            self._redirect("/web/login")
            return
        self._html(HTTPStatus.OK, render_users(
            self.server.users.all_users(),
            registration_open=self.server.config.registration_open, current_user=actor))

    def _web_images(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        blocks = [b.as_dict() for b in self.server.catalog().blocks()]
        self._html(HTTPStatus.OK, render_images(self._pool_image_rows(), blocks))

    def _web_history(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        query = parse_qs(urlsplit(self.path).query)
        user, ref = query.get("user", [""])[0], query.get("ref", [""])[0]
        record = self.server.progress().get(user).get(ref, {}) if user else {}
        self._html(HTTPStatus.OK, render_history(user, ref, record))

    def _web_ref_form(self) -> tuple[dict[str, str], str] | None:
        """Author-gate a POST, return (form, ref) if the ref exists, else redirect and return None."""
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return None
        form = self._form()
        ref = form.get("ref", "")
        if not ref or not self.server.store.exists(ref):
            self._redirect("/web/images")
            return None
        return form, ref

    def _web_image_describe(self) -> None:
        got = self._web_ref_form()
        if got is None:
            return
        form, ref = got
        with contextlib.suppress(ValueError, OSError):
            self.server.attachments().set_description(ref, form.get("description", "")[:_MAX_DESC])
        self._redirect("/web/images")

    def _web_image_attach(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        fields, files = _parse_multipart(self._read_body(), self.headers.get("Content-Type", ""))
        ref, part = fields.get("ref", ""), files.get("file")
        if ref and self.server.store.exists(ref) and part and part[1] and len(part[1]) <= _MAX_ATTACH:
            with contextlib.suppress(ValueError, OSError):
                self.server.attachments().put_file(ref, part[0], part[1])
        self._redirect("/web/images")

    def _web_image_attach_delete(self) -> None:
        got = self._web_ref_form()
        if got is None:
            return
        form, ref = got
        with contextlib.suppress(ValueError, OSError):
            self.server.attachments().delete_file(ref, form.get("name", ""))
        self._redirect("/web/images")

    def _web_attachment_download(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        query = parse_qs(urlsplit(self.path).query)
        ref, name = query.get("ref", [""])[0], query.get("name", [""])[0]
        try:
            blob = self.server.attachments().read_file(ref, name)
            safe = safe_filename(name)
        except (ValueError, FileNotFoundError, OSError):
            self._empty(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _web_catalog_add(self) -> None:
        got = self._web_ref_form()
        if got is None:
            return
        form, ref = got
        task_dir = self.server.store.get(ref).layer.parent / "task"
        if not task_dir.exists():   # only a task image (with a grader) can join the catalog
            self._redirect("/web/images")
            return
        self.server.catalog().add_task(ref, task_digest(task_dir),
                                       block_id=form.get("block_id") or None)
        self._redirect("/web/images")

    def _web_catalog_remove(self) -> None:
        got = self._web_ref_form()
        if got is None:
            return
        _form, ref = got
        self.server.catalog().remove_task(ref)
        self._redirect("/web/images")

    def _web_catalog_layout(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        data = self._json_body()
        if data is None or not isinstance(data.get("blocks"), list):
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        self.server.catalog().set_layout(data["blocks"])   # drag-and-drop reorder / move
        self._json(HTTPStatus.OK, {"ok": True})

    def _web_block_add(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        self.server.catalog().add_block(self._form().get("name", "").strip() or "Блок")
        self._redirect("/web/images")

    def _web_block_rename(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        form = self._form()
        self.server.catalog().rename_block(form.get("block_id", ""),
                                           form.get("name", "").strip() or "Блок")
        self._redirect("/web/images")

    def _web_block_remove(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        self.server.catalog().remove_block(self._form().get("block_id", ""))
        self._redirect("/web/images")

    def _web_block_toggle(self) -> None:
        if self._session_role(_AUTHOR_ROLES) is None:
            self._redirect("/web/login")
            return
        form = self._form()
        self.server.catalog().set_block_open(form.get("block_id", ""),
                                             open_=form.get("open", "") == "1")
        self._redirect("/web/images")

    def _web_password_form(self) -> None:
        if self._session_user() is None:
            self._redirect("/web/login")
            return
        self._html(HTTPStatus.OK, render_password_form())

    def _web_password_change(self) -> None:
        user = self._session_user()
        if user is None:
            self._redirect("/web/login")
            return
        form = self._form()
        new, confirm = form.get("new", ""), form.get("confirm", "")
        if not new or new != confirm:
            self._html(HTTPStatus.OK, render_password_form("новые пароли пусты или не совпадают"))
            return
        if not self.server.users.verify(user, form.get("old", "")):
            self._html(HTTPStatus.OK, render_password_form("неверный текущий пароль"))
            return
        try:
            validate_password(new)
        except WeakPasswordError as exc:
            self._html(HTTPStatus.OK, render_password_form(str(exc)))
            return
        self.server.users.set_password(user, new)
        self._html(HTTPStatus.OK, render_password_form(done=True))

    def _web_reset_link(self) -> None:
        if self._session_role(("admin",)) is None:
            self._redirect("/web/login")
            return
        target = self._form().get("user", "")
        if not self.server.users.has(target):
            self._redirect("/web/users")
            return
        token = issue_token(self.server.secret, _RESET_PREFIX + target,
                            now=time.time(), ttl=_RESET_TTL)
        self._html(HTTPStatus.OK,
                   render_reset_link(target, f"{self._pool_url()}/web/reset?token={token}"))

    def _web_reset_do(self) -> None:
        form = self._form()
        token = form.get("token", "")
        subject = verify_token(self.server.secret, token, now=time.time())
        if subject is None or not subject.startswith(_RESET_PREFIX):
            self._html(HTTPStatus.OK, render_reset_form(token, "ссылка недействительна или истекла"))
            return
        new, confirm = form.get("new", ""), form.get("confirm", "")
        if not new or new != confirm:
            self._html(HTTPStatus.OK, render_reset_form(token, "пароли пусты или не совпадают"))
            return
        try:
            validate_password(new)
        except WeakPasswordError as exc:
            self._html(HTTPStatus.OK, render_reset_form(token, str(exc)))
            return
        try:
            self.server.users.set_password(subject[len(_RESET_PREFIX):], new)
        except KeyError:
            self._html(HTTPStatus.OK, render_reset_form(token, "пользователь не найден"))
            return
        self._redirect("/web/login")

    def _web_login(self) -> None:
        form = self._form()
        user = form.get("user", "").strip()
        if (self.server.users.verify(user, form.get("password", ""))
                and self.server.users.role(user) in _AUTHOR_ROLES):
            token = issue_token(self.server.secret, user, now=time.time())
            self._redirect("/web", cookie=f"hp_session={token}; Path=/; HttpOnly; SameSite=Lax")
            return
        self._html(HTTPStatus.UNAUTHORIZED, render_login("Неверный логин/пароль или нет доступа."))

    def _web_set_role(self) -> None:
        actor = self._session_role(("admin",))
        if actor is None:
            self._redirect("/web/login")
            return
        form = self._form()
        target, role = form.get("user", "").strip(), form.get("role", "")
        if target != actor and role in ROLES and self.server.users.has(target):
            self.server.users.set_role(target, role)   # never change your own role (self-lockout)
        self._redirect("/web/users")

    def _web_delete_user(self) -> None:
        actor = self._session_role(("admin",))
        if actor is None:
            self._redirect("/web/login")
            return
        target = self._form().get("user", "").strip()
        if target and target != actor:                 # never delete yourself
            self.server.users.delete(target)
            self.server.progress().delete(target)
        self._redirect("/web/users")

    def _web_delete_group(self) -> None:
        actor = self._session_role(("admin",))
        if actor is None:
            self._redirect("/web/login")
            return
        group = self._form().get("group", "").strip()
        if group:
            prog = self.server.progress()
            for profile in self.server.users.all_users():
                user = str(profile["user"])
                if str(profile.get("group", "")) == group and user != actor:
                    self.server.users.delete(user)
                    prog.delete(user)
        self._redirect("/web/users")

    def _web_registration(self) -> None:
        if self._session_role(("admin",)) is None:
            self._redirect("/web/login")
            return
        self.server.config.registration_open = self._form().get("open") == "true"
        if self.server.config_path is not None:
            save_config(self.server.config_path, self.server.config)
        self._redirect("/web/users")

    def do_HEAD(self) -> None:
        target = self._image_parts()
        present = target is not None and self.server.store.exists(f"{target[0]}:{target[1]}")
        self._empty(HTTPStatus.OK if present else HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        if (att := self._parts_for("attachment")) is not None:
            self._put_attachment(f"{att[0]}:{att[1]}")   # /attachment/<name.../>/<version>?name=
        elif self._image_parts() is not None:
            self._put_image()
        elif (task := self._parts_for("task")) is not None:
            self._put_task(f"{task[0]}:{task[1]}")
        else:
            self._empty(HTTPStatus.NOT_FOUND)

    def _put_attachment(self, ref: str) -> None:
        _user, err = self._auth_role(_AUTHOR_ROLES)
        if err is not None:
            self._empty(err)
            return
        if not self.server.store.exists(ref):
            self._empty(HTTPStatus.NOT_FOUND)   # push the image before attaching to it
            return
        query = parse_qs(urlsplit(self.path).query)
        filename = query.get("name", [""])[0]
        body = self._read_body()
        if not filename or not body or len(body) > _MAX_ATTACH:
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        taskfile = query.get("taskfile", [""])[0] == "1"
        try:
            self.server.attachments().put_file(ref, filename, body, taskfile=taskfile)
        except (ValueError, OSError):
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        self._empty(HTTPStatus.CREATED)

    def _put_image(self) -> None:
        _user, err = self._auth_role(("author", "admin"))
        if err is not None:
            self._empty(err)
            return
        try:
            unpack_image(self._read_body(), self.server.store)
        except (ValueError, KeyError, OSError, tarfile.TarError):
            # ValueError also covers an unsafe (traversing) name/version from the blob (§5).
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        self._empty(HTTPStatus.CREATED)

    def _put_task(self, ref: str) -> None:
        _user, err = self._auth_role(("author", "admin"))
        if err is not None:
            self._empty(err)
            return
        if not self.server.store.exists(ref):
            self._empty(HTTPStatus.NOT_FOUND)  # push the image before its task
            return
        task_dir = self.server.store.get(ref).layer.parent / "task"
        try:
            unpack_task(self._read_body(), task_dir)
        except (ValueError, OSError, tarfile.TarError):
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        query = parse_qs(urlsplit(self.path).query)
        if query.get("publish", [""])[0] == "1":   # `push --task`: add it to the catalog (auto-number)
            self.server.catalog().add_task(ref, task_digest(task_dir))
        self._empty(HTTPStatus.CREATED)

    def _serve_closure(self, ref: str) -> None:
        try:
            refs = closure_refs(ref, self.server.store)
        except KeyError:
            self._empty(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"refs": refs})

    def _serve_image(self, ref: str) -> None:
        try:
            img = self.server.store.get(ref)
        except KeyError:
            self._empty(HTTPStatus.NOT_FOUND)
            return
        self._blob(HTTPStatus.OK, pack_image(img))

    def _serve_task(self, ref: str) -> None:
        if self._token_user() is None:
            self._empty(HTTPStatus.UNAUTHORIZED)  # a task's grader is not public
            return
        if not self.server.store.exists(ref):
            self._empty(HTTPStatus.NOT_FOUND)
            return
        task_dir = self.server.store.get(ref).layer.parent / "task"
        if not task_dir.exists():
            self._empty(HTTPStatus.NOT_FOUND)
            return
        self._blob(HTTPStatus.OK, pack_task(task_dir))


def make_server(store: ImageStore, users: UserStore, secret: bytes, *,  # noqa: PLR0913
                host: str = "127.0.0.1", port: int = 0,
                config: ServerConfig | None = None,
                config_path: Path | None = None,
                catalog_path: Path | None = None,
                progress_path: Path | None = None, attachments_path: Path | None = None,
                certfile: Path | None = None, keyfile: Path | None = None) -> RegistryServer:
    """
    Create a pool registry server (port 0 = ephemeral). Default host is loopback.

    With `certfile`+`keyfile`, the listening socket is TLS-wrapped (HTTPS) via stdlib `ssl`.
    """
    server = RegistryServer((host, port), store=store, users=users, secret=secret,
                            config=config, config_path=config_path, catalog_path=catalog_path,
                            progress_path=progress_path, attachments_path=attachments_path)
    if certfile is not None and keyfile is not None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(certfile), str(keyfile))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    return server
