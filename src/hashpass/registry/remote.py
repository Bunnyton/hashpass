"""
HTTP client to a pool registry server (stdlib urllib). Anonymous pull; mutations need a token.

Point base_url at your pool (loopback in tests, or the self-hosted pool). It must never be the
legacy server (no 185.x). Tokens are cached locally and reused until they expire.
"""
import json
import os
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from time import time

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image, pack_task, unpack_image, unpack_task
from hashpass.registry.creds import CredentialCache
from hashpass.registry.refs import closure_refs, normalize_ref, split_ref
from hashpass.registry.token import token_expiry

_TIMEOUT = 30
_ALLOWED_SCHEMES = ("http://", "https://")

# The pool is reached directly (loopback in tests), so this client must NOT route through an
# ambient HTTP(S)_PROXY -- a sandbox/corp proxy would intercept 127.0.0.1 and answer 500. An empty
# ProxyHandler disables proxying for every request. For an HTTPS pool: HASHPASS_TLS_CAFILE trusts a
# CA (e.g. a self-signed cert), HASHPASS_TLS_INSECURE=1 skips verification entirely (self-signed dev).
def _build_opener() -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    cafile = os.environ.get("HASHPASS_TLS_CAFILE")
    if os.environ.get("HASHPASS_TLS_INSECURE"):
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))  # noqa: S323, SLF001
    elif cafile:
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=cafile)))
    return urllib.request.build_opener(*handlers)


_DIRECT = _build_opener()


@dataclass
class RemoteRegistry:
    """HTTP pool client: anonymous pull, token-gated push/register/submit. Never point at 185.x."""

    base_url: str
    cache: CredentialCache | None = None
    sudo: bool = False

    def _url(self, path: str) -> str:
        if not self.base_url.startswith(_ALLOWED_SCHEMES):
            msg = f"registry base_url must be http(s): {self.base_url!r}"
            raise ValueError(msg)
        return f"{self.base_url.rstrip('/')}{path}"

    def _open(self, req: urllib.request.Request) -> bytes:
        with _DIRECT.open(req, timeout=_TIMEOUT) as resp:  # localhost only, no proxy
            return resp.read()

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
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(path), data=json.dumps(payload).encode("utf-8"), method="POST",
            headers=headers,
        )
        raw = self._open(req)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _get_json(self, path: str, *, token: str | None = None) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(path), method="GET", headers=headers,
        )
        return json.loads(self._open(req).decode("utf-8"))

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

    def push(self, store: ImageStore, ref: str, *, token: str | None = None) -> list[str]:
        """Push ref + its `from` closure (bottom-up), skipping refs the server already holds."""
        auth = self._push_token(token)
        copied: list[str] = []
        for item in closure_refs(ref, store):
            if self._has_image(item):
                continue
            name, version = split_ref(item)
            self._put_image(name, version, pack_image(store.get(item)), auth)
            copied.append(item)
        return copied

    def pull(self, ref: str, store: ImageStore) -> list[str]:
        """Pull ref + its `from` closure (bottom-up) anonymously, skipping refs already local."""
        copied: list[str] = []
        for item in self._closure(normalize_ref(ref)):
            if store.exists(item):
                continue
            unpack_image(self._get_image(item), store, sudo=self.sudo)
            copied.append(item)
        return copied

    def closure(self, ref: str) -> list[str]:
        """Return a ref's bottom-up `from` closure from the pool."""
        return self._closure(normalize_ref(ref))

    def pull_many(self, refs: list[str], store: ImageStore, *, workers: int = 8) -> list[str]:
        """
        Pull several refs + their closures concurrently; each missing layer is fetched once.

        Downloads run in a thread pool; the (fast) local save is serialized under a lock so
        shared parent layers are never written twice. Returns the layers actually fetched.
        """
        needed: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            for item in self._closure(normalize_ref(ref)):
                if item not in seen:
                    seen.add(item)
                    needed.append(item)
        to_fetch = [item for item in needed if not store.exists(item)]
        lock = threading.Lock()
        fetched: list[str] = []

        def _one(item: str) -> None:
            blob = self._get_image(item)          # network download (parallel)
            with lock:                            # local save (serialized: no shared-parent race)
                if store.exists(item):
                    return
                unpack_image(blob, store, sudo=self.sudo)
                fetched.append(item)

        if to_fetch:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_one, to_fetch))
        return fetched

    def push_task(self, task_dir: Path, name: str, version: str, *,  # noqa: PLR0913
                  number: int | None = None, title: str = "", token: str | None = None) -> None:
        """Push a task's artifacts to the pool; with `number`, also claim that catalog slot."""
        query = ""
        if number is not None:
            query = "?" + urllib.parse.urlencode({"number": number, "title": title})
        self._put_task(name, version, query, pack_task(task_dir), self._auth_token(token))

    def catalog(self, *, token: str | None = None) -> list[dict[str, object]]:
        """Return the ordered task catalog (requires a login token)."""
        result = self._get_json("/catalog", token=self._auth_token(token))
        return list(result.get("catalog", []))

    def pool_images(self, *, token: str | None = None) -> list[dict[str, object]]:
        """List images/tasks stored on the pool: each {ref, kind, number?} (requires a token)."""
        result = self._get_json("/images", token=self._auth_token(token))
        return list(result.get("images", []))

    def submit(self, task_ref: str, digest: str, *,
               passed: bool, token: str | None = None) -> dict[str, object]:
        """Submit a task result; returns {status, global_key?} (digest-gated, principal-bound)."""
        return self._post_json("/submit", {"task_ref": task_ref, "digest": digest, "passed": passed},
                               token=self._auth_token(token))

    def progress(self, *, token: str | None = None) -> dict[str, object]:
        """Return progress: an author sees every student; a student sees only their own."""
        result = self._get_json("/progress", token=self._auth_token(token))
        return dict(result.get("progress", {}))

    def pull_task(self, ref: str, dest_task_dir: Path, *, token: str | None = None) -> None:
        """Pull a task's artifacts into dest_task_dir (requires a login token)."""
        unpack_task(self._get_task(ref, token=self._auth_token(token)), dest_task_dir)

    def _put_task(self, name: str, version: str, query: str,
                  blob: bytes, token: str) -> None:
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(f"/task/{name}/{version}{query}"), data=blob, method="PUT",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/octet-stream"},
        )
        self._open(req)

    def _get_task(self, ref: str, *, token: str) -> bytes:
        name, version = split_ref(ref)
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(f"/task/{name}/{version}"), method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        return self._open(req)

    def _closure(self, ref: str) -> list[str]:
        name, version = split_ref(ref)
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(f"/closure/{name}/{version}"), method="GET",
        )
        return json.loads(self._open(req).decode("utf-8"))["refs"]

    def _get_image(self, ref: str) -> bytes:
        name, version = split_ref(ref)
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(f"/image/{name}/{version}"), method="GET",
        )
        return self._open(req)

    def _has_image(self, ref: str) -> bool:
        name, version = split_ref(ref)
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(f"/image/{name}/{version}"), method="HEAD",
        )
        try:
            self._open(req)
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.NOT_FOUND:
                return False
            raise
        return True

    def _put_image(self, name: str, version: str, blob: bytes, token: str) -> None:
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url(f"/image/{name}/{version}"), data=blob, method="PUT",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/octet-stream"},
        )
        self._open(req)
