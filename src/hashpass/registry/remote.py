"""
HTTP client to a pool registry server (stdlib urllib). Anonymous pull; mutations need a token.

Point base_url at your pool (loopback in tests, or the self-hosted pool). It must never be the
legacy server (no 185.x). Tokens are cached locally and reused until they expire.
"""
import hashlib
import json
import os
import shutil
import ssl
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from time import time
from typing import BinaryIO

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import (
    inspect_image_blob,
    pack_image_to_file,
    pack_task,
    unpack_image_file,
    unpack_task,
)
from hashpass.registry.creds import CredentialCache
from hashpass.registry.refs import closure_refs, normalize_ref, split_ref
from hashpass.registry.token import token_expiry

_TIMEOUT = 30
_DIGEST_HEADER = "X-Image-Digest"
_COPY_CHUNK = 1 << 20

# The pool is reached directly (loopback in tests), so this client must NOT route through an
# ambient HTTP(S)_PROXY -- a sandbox/corp proxy would intercept 127.0.0.1 and answer 500. An empty
# ProxyHandler disables proxying for every request. For an HTTPS pool: a self-signed certificate is
# accepted automatically (the common teaching-pool setup); HASHPASS_TLS_CAFILE pins a specific CA
# (and then a bad cert is NOT silently accepted), HASHPASS_TLS_INSECURE=1 forces no verification.
def _build_opener(*, insecure: bool = False) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    cafile = os.environ.get("HASHPASS_TLS_CAFILE")
    if insecure or os.environ.get("HASHPASS_TLS_INSECURE"):
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))  # noqa: S323, SLF001
    elif cafile:
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=cafile)))
    return urllib.request.build_opener(*handlers)


_DIRECT = _build_opener()
_DIRECT_INSECURE = _build_opener(insecure=True)   # retried opener that trusts a self-signed pool


def _is_cert_error(exc: Exception) -> bool:
    """Whether exc is a TLS certificate-verification failure (self-signed / untrusted CA)."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return isinstance(reason, ssl.SSLCertVerificationError)


def _not_found_error(exc: urllib.error.HTTPError, ref: str) -> RuntimeError | None:
    """
    Turn a pool 404 into a readable RuntimeError (with the pool's «быть может, вы искали …?»).

    Any other status yields None: the caller re-raises its HTTPError untouched.
    """
    if exc.code != HTTPStatus.NOT_FOUND:
        return None
    try:
        payload = json.loads(exc.read())
    except (ValueError, UnicodeDecodeError, OSError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), str) and payload["error"]:
        return RuntimeError(payload["error"])
    return RuntimeError(f"образ «{ref}» не найден на пуле")


@dataclass
class RemoteRegistry:
    """HTTP pool client: anonymous pull, token-gated push/register/submit. Never point at 185.x."""

    base_url: str
    cache: CredentialCache | None = None
    sudo: bool = False
    _resolved_base: str | None = field(default=None, init=False, repr=False, compare=False)
    # Downloads run in parallel (pull_many); the local unpack+meta write is serialized.
    _unpack_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False,
                                         compare=False)

    def _bases(self) -> list[str]:
        """
        Candidate base URLs to try, best first, so the user need not spell out the scheme.

        A base resolved by a prior successful call is reused. Otherwise: no scheme -> try https
        then http; a bare http:// -> try it, then https:// (an http->https fallback for a
        TLS-only pool); an explicit https:// is used as given (never downgraded to plain http).
        """
        if self._resolved_base:
            return [self._resolved_base]
        raw = self.base_url.rstrip("/")
        if raw.startswith("https://"):
            return [raw]
        if raw.startswith("http://"):
            return [raw, "https://" + raw[len("http://"):]]
        return ["https://" + raw, "http://" + raw]

    def _open_once(self, req: urllib.request.Request,
                   sink: BinaryIO | None = None) -> tuple[bytes, dict[str, str]]:
        """Open one request; return (body, headers). With `sink`, stream the body there instead."""
        def _drain(resp) -> tuple[bytes, dict[str, str]]:
            headers = dict(resp.headers.items())
            if sink is None:
                return resp.read(), headers
            shutil.copyfileobj(resp, sink, _COPY_CHUNK)
            return b"", headers
        try:
            with _DIRECT.open(req, timeout=_TIMEOUT) as resp:
                return _drain(resp)
        except urllib.error.HTTPError:
            raise                                   # a real HTTP status -> callers handle it
        except (urllib.error.URLError, ssl.SSLError) as exc:
            if os.environ.get("HASHPASS_TLS_CAFILE") or not _is_cert_error(exc):
                raise
            with _DIRECT_INSECURE.open(req, timeout=_TIMEOUT) as resp:   # self-signed: trust it
                return _drain(resp)

    def _request(self, method: str, path: str, *, data: bytes | BinaryIO | None = None,
                 headers: dict[str, str] | None = None,
                 sink: BinaryIO | None = None) -> tuple[bytes, dict[str, str]]:
        """
        Like the old _send, but also returns response headers and can stream to `sink`.

        Auto-selects http/https; the first scheme that connects is cached for the rest of
        this client's life.
        """
        last: Exception | None = None
        for base in self._bases():
            if hasattr(data, "seek"):
                data.seek(0)                        # a retried upload restarts the file
            req = urllib.request.Request(  # noqa: S310  (scheme is http/https by construction)
                f"{base}{path}", data=data, method=method, headers=dict(headers or {}))
            try:
                out = self._open_once(req, sink)
            except urllib.error.HTTPError:
                self._resolved_base = base          # the server answered -> this scheme is right
                raise
            except (urllib.error.URLError, ssl.SSLError, ConnectionError) as exc:
                last = exc                          # this scheme did not connect -> try the next
                if sink is not None:
                    sink.seek(0)
                    sink.truncate()
                continue
            self._resolved_base = base
            return out
        msg = (f"не удалось подключиться к пулу {self.base_url}: {last}. "
               "Проверьте адрес и что пул запущен.")
        raise RuntimeError(msg) from last

    def _send(self, method: str, path: str, *, data: bytes | None = None,
              headers: dict[str, str] | None = None) -> bytes:
        """Send a request, discarding response headers (thin wrapper over `_request`)."""
        return self._request(method, path, data=data, headers=headers)[0]

    def _cache_token(self, token: str) -> None:
        expiry = token_expiry(token)
        if self.cache is not None and expiry is not None:
            self.cache.save(self.base_url, token, expiry)

    def _auth_token(self, token: str | None) -> str:
        if token is not None:
            return token
        if self.cache is not None:
            cached = self.cache.cached_token(self.base_url, now=time())
            if cached is not None:
                return cached
        msg = "this action requires a token; call login(...)/register(...) first"
        raise ValueError(msg)

    def _post_json(self, path: str, payload: dict[str, object],
                   *, token: str | None = None) -> dict[str, object]:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        raw = self._send("POST", path, data=json.dumps(payload).encode("utf-8"), headers=headers)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _get_json(self, path: str, *, token: str | None = None) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return json.loads(self._send("GET", path, headers=headers).decode("utf-8"))

    def login(self, user: str, password: str) -> str:
        """Authenticate; cache and return a signed token. Server checks the PBKDF2 hash."""
        token = str(self._post_json("/login", {"user": user, "password": password})["token"])
        self._cache_token(token)
        return token

    def register(self, user: str, password: str, group: str, comment: str = "") -> str:
        """Register a new student (group required, comment free-form); cache and return the token."""
        token = str(self._post_json("/register", {
            "user": user, "password": password, "group": group, "comment": comment})["token"])
        self._cache_token(token)
        return token

    def user_exists(self, user: str) -> bool:
        """Return whether a login exists on the pool (public; enumeration is intentional)."""
        try:
            return bool(self._get_json(f"/users/{user}/exists").get("exists"))
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, ValueError):
            return True   # unknown -> assume yes and let the normal login flow proceed

    def me(self, *, token: str | None = None) -> dict[str, object]:
        """Return the authenticated user's profile {user, role, full_name, group, …}."""
        return self._get_json("/me", token=self._auth_token(token))

    def set_registration(self, *, open_: bool, token: str | None = None) -> dict[str, object]:
        """Admin: open or close self-registration on the pool."""
        return self._post_json("/admin/registration", {"open": open_},
                               token=self._auth_token(token))

    def set_role(self, user: str, role: str, *, token: str | None = None) -> dict[str, object]:
        """Admin: set a user's role (student/author/admin)."""
        return self._post_json("/admin/role", {"user": user, "role": role},
                               token=self._auth_token(token))

    def _push_token(self, token: str | None) -> str:
        return self._auth_token(token)

    def closure(self, ref: str) -> list[str]:
        """Return a ref's bottom-up `from` closure from the pool."""
        return self._closure(normalize_ref(ref))

    # --- images -----------------------------------------------------------------

    def has_image(self, ref: str) -> bool:
        """Whether the pool holds `ref` (HEAD)."""
        name, version = split_ref(ref)
        try:
            self._request("HEAD", f"/image/{name}/{version}")
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                return False
            raise
        return True

    _has_image = has_image   # backwards-compatible name

    def image_digest(self, ref: str) -> str | None:
        """Return the pool's digest for `ref`; None when absent OR a legacy record without a digest."""
        name, version = split_ref(ref)
        try:
            _body, headers = self._request("HEAD", f"/image/{name}/{version}")
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                return None
            raise
        return headers.get(_DIGEST_HEADER) or None

    def download_image(self, ref: str, dest: Path) -> str:
        """
        Stream `ref`'s blob into `dest`, verifying sha256 against X-Image-Digest when present.

        Returns the digest ("" for a legacy record). On mismatch `dest` is removed and
        ValueError("digest mismatch …") is raised -- a torn download must never be unpacked.
        """
        name, version = split_ref(ref)
        with dest.open("wb") as sink:
            _body, headers = self._request("GET", f"/image/{name}/{version}", sink=sink)
        expected = headers.get(_DIGEST_HEADER, "")
        if not expected:
            return ""
        h = hashlib.sha256()
        with dest.open("rb") as f:
            for chunk in iter(lambda: f.read(_COPY_CHUNK), b""):
                h.update(chunk)
        if h.hexdigest() != expected:
            dest.unlink(missing_ok=True)
            msg = f"digest mismatch for {ref}: pool says {expected[:12]}…, got {h.hexdigest()[:12]}…"
            raise ValueError(msg)
        return expected

    def _get_image(self, ref: str) -> bytes:              # kept for tests / small images
        name, version = split_ref(ref)
        return self._send("GET", f"/image/{name}/{version}")

    def _wants(self, ref: str, store: ImageStore, *, refresh: bool) -> bool:
        """Whether `ref` needs fetching: missing locally, or (`refresh`) present but digest-stale."""
        if not store.exists(ref):
            return True
        if not refresh:
            return False
        remote = self.image_digest(ref)
        return remote is not None and remote != store.get(ref).pool_digest

    def _pull_one(self, item: str, store: ImageStore, *, refresh: bool) -> bool:
        """
        Download one ref's blob into `<store>/.incoming/`, check it, unpack it; True if stored.

        The blob must declare exactly the requested ref (the server validates this only on
        PUT; a tampered pool could otherwise plant another name in the store). The temp file
        is removed on every path. Without `refresh`, a ref another worker stored meanwhile is
        skipped.
        """
        incoming = store.root / ".incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=incoming, suffix=".tar.gz", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            digest = self.download_image(item, path)          # network (parallel in pull_many)
            info = inspect_image_blob(path)                   # structure only, no extraction
            declared, requested = f"{info.name}:{info.version}", normalize_ref(item)
            if declared != requested:
                msg = f"pool served {declared} for {requested}"
                raise ValueError(msg)
            with self._unpack_lock:                           # local unpack, serialized
                if not refresh and store.exists(item):
                    return False
                unpack_image_file(path, store, sudo=(True if self.sudo else None))
                if digest:
                    store.set_pool_digest(item, digest, registry=self.base_url)
            return True
        finally:
            path.unlink(missing_ok=True)

    def pull(self, ref: str, store: ImageStore, *, refresh: bool = False) -> list[str]:
        """Pull ref + its `from` closure (bottom-up), skipping refs already local (unless stale)."""
        # sequential and in closure order: each item is checked and fetched before the next
        return [item for item in self._closure(normalize_ref(ref))
                if self._wants(item, store, refresh=refresh)
                and self._pull_one(item, store, refresh=True)]

    def pull_many(self, refs: list[str], store: ImageStore, *, workers: int = 8,
                  refresh: bool = False) -> list[str]:
        """Pull several refs + closures concurrently; `refresh` also re-pulls digest-stale ones."""
        needed: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            for item in self._closure(normalize_ref(ref)):
                if item not in seen:
                    seen.add(item)
                    needed.append(item)
        to_fetch = [item for item in needed if self._wants(item, store, refresh=refresh)]
        if not to_fetch:
            return []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            stored = list(pool.map(lambda item: self._pull_one(item, store, refresh=refresh),
                                   to_fetch))
        return [item for item, ok in zip(to_fetch, stored, strict=True) if ok]

    def push(self, store: ImageStore, ref: str, *, token: str | None = None,
             force: bool = False) -> list[str]:
        # `force=False` (default) skips refs the server already holds via a HEAD probe --
        # the fast path.  `force=True` uploads every layer regardless, needed to overwrite
        # a contaminated server-side blob (HEAD says the ref exists, so fresh bytes never
        # reach the store otherwise).
        """Push ref + its `from` closure (bottom-up); each blob is packed to disk and streamed."""
        auth = self._push_token(token)
        copied: list[str] = []
        for item in closure_refs(ref, store):
            if not force and self.has_image(item):
                continue
            name, version = split_ref(item)
            with tempfile.TemporaryDirectory() as td:
                blob = pack_image_to_file(store.get(item), Path(td) / "image.tar.gz")
                digest = self._put_image_file(name, version, blob, auth)
            if digest:                      # remember what THIS pool now holds for this ref
                store.set_pool_digest(item, digest, registry=self.base_url)
            copied.append(item)
        return copied

    def _put_image_file(self, name: str, version: str, blob: Path, token: str) -> str | None:
        """PUT one packed blob; return the digest the pool assigned to it (None on old pools)."""
        with blob.open("rb") as f:
            _body, headers = self._request(
                "PUT", f"/image/{name}/{version}", data=f,
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/octet-stream",
                         "Content-Length": str(blob.stat().st_size)})
        return headers.get(_DIGEST_HEADER) or None

    def _put_image(self, name: str, version: str, blob: bytes, token: str) -> None:   # kept for tests
        self._send("PUT", f"/image/{name}/{version}", data=blob,
                   headers={"Authorization": f"Bearer {token}",
                            "Content-Type": "application/octet-stream"})

    def push_task(self, task_dir: Path, name: str, version: str, *,
                  publish: bool = False, token: str | None = None) -> None:
        """Push a task's artifacts to the pool; with `publish`, also add it to the catalog."""
        query = "?publish=1" if publish else ""
        self._put_task(name, version, query, pack_task(task_dir), self._auth_token(token))

    def push_attachment(self, name: str, version: str, filename: str, blob: bytes, *,  # noqa: PLR0913
                        taskfile: bool = False, token: str | None = None) -> None:
        """Attach a file (e.g. the Taskfile) to an image's pool card (author-only)."""
        params = {"name": filename}
        if taskfile:
            params["taskfile"] = "1"
        query = "?" + urllib.parse.urlencode(params)
        self._send("PUT", f"/attachment/{name}/{version}{query}", data=blob,
                   headers={"Authorization": f"Bearer {self._auth_token(token)}",
                            "Content-Type": "application/octet-stream"})

    def set_catalog_layout(self, blocks: list[dict[str, object]], *,
                           token: str | None = None) -> dict[str, object]:
        """Set the pool's catalog layout (admin); return {"catalog": numbered rows, "removed": refs}."""
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self._auth_token(token)}"}
        raw = self._send("PUT", "/catalog/layout", data=json.dumps({"blocks": blocks}).encode("utf-8"),
                         headers=headers)
        return json.loads(raw.decode("utf-8")) if raw else {"catalog": [], "removed": []}

    def catalog(self, *, token: str | None = None) -> list[dict[str, object]]:
        """Return the ordered task catalog (requires a login token)."""
        result = self._get_json("/catalog", token=self._auth_token(token))
        return list(result.get("catalog", []))

    def pool_images(self, *, token: str | None = None) -> list[dict[str, object]]:
        """List images/tasks stored on the pool: each {ref, kind, number?} (requires a token)."""
        result = self._get_json("/images", token=self._auth_token(token))
        return list(result.get("images", []))

    def submit(self, task_ref: str, digest: str, *, passed: bool,  # noqa: PLR0913
               history: list[dict[str, object]] | None = None,
               authenticity: dict[str, object] | None = None,
               token: str | None = None) -> dict[str, object]:
        """Submit a task result (+ optional command history / anti-bot signal); returns {status,...}."""
        payload: dict[str, object] = {"task_ref": task_ref, "digest": digest, "passed": passed}
        if history is not None:
            payload["history"] = history
        if authenticity is not None:
            payload["authenticity"] = authenticity
        return self._post_json("/submit", payload, token=self._auth_token(token))

    def progress(self, *, token: str | None = None) -> dict[str, object]:
        """Return progress: an author sees every student; a student sees only their own."""
        result = self._get_json("/progress", token=self._auth_token(token))
        return dict(result.get("progress", {}))

    def pull_task(self, ref: str, dest_task_dir: Path, *, token: str | None = None) -> None:
        """Pull a task's artifacts into dest_task_dir (requires a login token)."""
        unpack_task(self._get_task(ref, token=self._auth_token(token)), dest_task_dir)

    def _put_task(self, name: str, version: str, query: str,
                  blob: bytes, token: str) -> None:
        self._send("PUT", f"/task/{name}/{version}{query}", data=blob,
                   headers={"Authorization": f"Bearer {token}",
                            "Content-Type": "application/octet-stream"})

    def _get_task(self, ref: str, *, token: str) -> bytes:
        name, version = split_ref(ref)
        try:
            return self._send("GET", f"/task/{name}/{version}",
                              headers={"Authorization": f"Bearer {token}"})
        except urllib.error.HTTPError as exc:
            err = _not_found_error(exc, ref)
            if err is None:
                raise
            raise err from exc

    def _closure(self, ref: str) -> list[str]:
        name, version = split_ref(ref)
        try:
            body = self._send("GET", f"/closure/{name}/{version}")
        except urllib.error.HTTPError as exc:
            err = _not_found_error(exc, ref)
            if err is None:
                raise
            raise err from exc
        return json.loads(body.decode("utf-8"))["refs"]
