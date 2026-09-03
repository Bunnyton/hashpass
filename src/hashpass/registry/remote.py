"""
HTTP client to a registry server (stdlib urllib). Anonymous pull; push needs a login token.

SECURITY BOUNDARY: point base_url at a localhost server for tests ONLY. Never push to a real
remote (no 185.x). Tokens are cached locally and reused until they expire.
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from time import time

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image, unpack_image
from hashpass.registry.creds import CredentialCache
from hashpass.registry.refs import closure_refs, normalize_ref, split_ref
from hashpass.registry.token import token_expiry

_TIMEOUT = 30
_ALLOWED_SCHEMES = ("http://", "https://")

# This client only ever talks to a localhost registry (see the SECURITY BOUNDARY above), so it
# must NOT route through an ambient HTTP(S)_PROXY -- a sandbox/corp proxy would intercept
# 127.0.0.1 and answer 500. An empty ProxyHandler disables proxying for every request.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class RemoteRegistry:
    """HTTP registry client: anon pull, token-gated push. Localhost/dev/test only, never shipped."""

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

    def login(self, user: str, password: str) -> str:
        """Authenticate; cache and return a signed token. Server checks the PBKDF2 hash."""
        body = json.dumps({"user": user, "password": password}).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310  (scheme guarded in _url)
            self._url("/login"), data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        token = json.loads(self._open(req).decode("utf-8"))["token"]
        expiry = token_expiry(token)
        if self.cache is not None and expiry is not None:
            self.cache.save(self.base_url, token, expiry)
        return token

    def _push_token(self, token: str | None) -> str:
        if token is not None:
            return token
        if self.cache is not None:
            cached = self.cache.cached_token(self.base_url, now=time())
            if cached is not None:
                return cached
        msg = "push requires a token; call login(user, password) first"
        raise ValueError(msg)

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
