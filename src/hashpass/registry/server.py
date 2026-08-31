"""
Local registry HTTP server (stdlib http.server).

SECURITY BOUNDARY: run on localhost for tests ONLY. It holds the signing secret and the
password hashes — like sync.LocalSyncClient it is a dev/test model of the server side and is
NEVER deployed (no 185.x) and NEVER used to push to a real remote.
"""
import json
import tarfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image, unpack_image
from hashpass.registry.passwords import UserStore
from hashpass.registry.refs import closure_refs
from hashpass.registry.token import issue_token, verify_token

_BEARER = "Bearer "
_IMAGE_PARTS = 3
_MAX_BODY = 512 * 1024 * 1024  # cap request bodies (localhost test server) to avoid memory blowup


class RegistryServer(ThreadingHTTPServer):
    """A localhost registry server holding the HMAC secret. Dev/test only, never shipped."""

    def __init__(self, address: tuple[str, int], *, store: ImageStore, users: UserStore,
                 secret: bytes) -> None:
        """Bind the server with its backing image store, user store, and HMAC secret."""
        super().__init__(address, _Handler)
        self.store = store
        self.users = users
        self.secret = secret


class _Handler(BaseHTTPRequestHandler):
    """Routes /login, /closure/<name>/<ver>, and /image/<name>/<ver> (GET/HEAD/PUT)."""

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence per-request stderr logging during tests."""

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

    def _token_user(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith(_BEARER):
            return None
        return verify_token(self.server.secret, auth[len(_BEARER):], now=time.time())

    def _image_parts(self) -> tuple[str, str] | None:
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) == _IMAGE_PARTS and parts[0] == "image":
            return parts[1], parts[2]
        return None

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/login":
            self._empty(HTTPStatus.NOT_FOUND)
            return
        try:
            creds = json.loads(self._read_body().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._empty(HTTPStatus.BAD_REQUEST)
            return
        user = str(creds.get("user", ""))
        if not self.server.users.verify(user, str(creds.get("password", ""))):
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        token = issue_token(self.server.secret, user, now=time.time())
        self._json(HTTPStatus.OK, {"token": token})

    def do_GET(self) -> None:
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) == _IMAGE_PARTS and parts[0] == "closure":
            self._serve_closure(f"{parts[1]}:{parts[2]}")
        elif (target := self._image_parts()) is not None:
            self._serve_image(f"{target[0]}:{target[1]}")
        else:
            self._empty(HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:
        target = self._image_parts()
        present = target is not None and self.server.store.exists(f"{target[0]}:{target[1]}")
        self._empty(HTTPStatus.OK if present else HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        if self._image_parts() is None:
            self._empty(HTTPStatus.NOT_FOUND)
            return
        if self._token_user() is None:
            self._empty(HTTPStatus.UNAUTHORIZED)
            return
        try:
            unpack_image(self._read_body(), self.server.store)
        except (ValueError, KeyError, OSError, tarfile.TarError):
            # ValueError also covers an unsafe (traversing) name/version from the blob (§5).
            self._empty(HTTPStatus.BAD_REQUEST)
            return
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


def make_server(store: ImageStore, users: UserStore, secret: bytes, *,
                host: str = "127.0.0.1", port: int = 0) -> RegistryServer:
    """Create a localhost registry server (port 0 = ephemeral). Binds localhost — test use ONLY."""
    return RegistryServer((host, port), store=store, users=users, secret=secret)
