"""
Pool registry HTTP server (stdlib http.server): image/task blobs + auth + roles + registration.

Binds a configurable host (default loopback). It holds the signing secret and the password
hashes, so every mutating or credit-granting request requires a valid bearer token, and role-gated
endpoints check the caller's role. It may be self-hosted as the pool; it must still NEVER be pointed
at or used to touch the legacy server (no 185.x).
"""
import json
import tarfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image, pack_task, unpack_image, unpack_task
from hashpass.registry.catalog import Catalog, CatalogEntry
from hashpass.registry.config import ServerConfig, save_config
from hashpass.registry.passwords import ROLES, UserStore
from hashpass.registry.refs import closure_refs
from hashpass.registry.token import issue_token, verify_token
from hashpass.taskdigest import task_digest

_BEARER = "Bearer "
_MIN_IMAGE_PARTS = 3  # /<kind>/<name.../>/<version>: kind + >=1 name segment + version
_MAX_BODY = 512 * 1024 * 1024  # cap request bodies to avoid memory blowup
_REQUIRED_PROFILE = ("full_name", "group")  # mandatory at registration (ФИО + учебная группа)


class RegistryServer(ThreadingHTTPServer):
    """A pool registry server holding the HMAC secret, user store, and runtime config."""

    def __init__(self, address: tuple[str, int], *, store: ImageStore,  # noqa: PLR0913
                 users: UserStore, secret: bytes, config: ServerConfig | None = None,
                 config_path: Path | None = None, catalog_path: Path | None = None) -> None:
        """Bind the server with its image store, user store, HMAC secret, config, and catalog."""
        super().__init__(address, _Handler)
        self.store = store
        self.users = users
        self.secret = secret
        self.config = config or ServerConfig()
        self.config_path = config_path
        self.catalog_path = catalog_path

    def catalog(self) -> Catalog:
        """Return a Catalog over this server's catalog file (a temp path if none was set)."""
        return Catalog(self.catalog_path or (Path(self.store.root) / "catalog.json"))


class _Handler(BaseHTTPRequestHandler):
    """Routes: POST /login /register /admin/registration /admin/role; GET /me /closure /image; PUT /image."""

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

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/login":
            self._login()
        elif path == "/register":
            self._register()
        elif path == "/admin/registration":
            self._admin_registration()
        elif path == "/admin/role":
            self._admin_role()
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
        profile = {field: str(data.get(field, "")).strip() for field in _REQUIRED_PROFILE}
        if not user or not password or not all(profile.values()):
            self._empty(HTTPStatus.BAD_REQUEST)  # login/password + ФИО + группа are mandatory
            return
        if self.server.users.has(user):
            self._empty(HTTPStatus.CONFLICT)
            return
        self.server.users.add(user, password, role="student", comment=str(data.get("comment", "")),
                              **profile)
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
        try:
            self.server.users.set_role(target, role)
        except KeyError:
            self._empty(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"user": target, "role": role})

    # -- GET / HEAD / PUT --------------------------------------------------

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/me":
            self._me()
            return
        if path == "/catalog":
            self._catalog()
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
        self._json(HTTPStatus.OK,
                   {"catalog": [e.as_dict() for e in self.server.catalog().entries()]})

    def do_HEAD(self) -> None:
        target = self._image_parts()
        present = target is not None and self.server.store.exists(f"{target[0]}:{target[1]}")
        self._empty(HTTPStatus.OK if present else HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        if self._image_parts() is not None:
            self._put_image()
        elif (task := self._parts_for("task")) is not None:
            self._put_task(f"{task[0]}:{task[1]}")
        else:
            self._empty(HTTPStatus.NOT_FOUND)

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
        number = query.get("number", [""])[0]
        if number:  # register/overwrite this task's catalog slot with a server-computed digest
            name, version = ref.rsplit(":", 1)
            title = query.get("title", [""])[0]
            try:
                slot = int(number)
            except ValueError:
                self._empty(HTTPStatus.BAD_REQUEST)
                return
            self.server.catalog().put(
                CatalogEntry(slot, name, version, title, task_digest(task_dir)))
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
                catalog_path: Path | None = None) -> RegistryServer:
    """Create a pool registry server (port 0 = ephemeral). Default host is loopback."""
    return RegistryServer((host, port), store=store, users=users, secret=secret,
                          config=config, config_path=config_path, catalog_path=catalog_path)
