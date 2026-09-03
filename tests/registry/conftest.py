"""Shared fixture for registry tests: a localhost registry server in a background thread."""
import secrets
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.passwords import UserStore
from hashpass.registry.server import make_server

_SECRET = secrets.token_bytes(32)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Neutralize any ambient HTTP(S)_PROXY for the localhost registry tests.

    A sandbox/corp proxy set in the environment intercepts even 127.0.0.1 and answers 500;
    these tests (and the client) only ever talk to a localhost server, so proxying is wrong.
    RemoteRegistry disables proxies itself; this covers the tests' own raw urllib helpers.
    """
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "*")


@dataclass
class RunningRegistry:
    """A live localhost registry server plus its backing image store and user store."""

    base_url: str
    store: ImageStore
    users: UserStore


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[RunningRegistry]:
    """Start a localhost registry server on an ephemeral port; shut it down on teardown."""
    store = ImageStore(tmp_path / "srv")
    users = UserStore(tmp_path / "users.json")
    server = make_server(store, users, _SECRET)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield RunningRegistry(f"http://{host}:{port}", store, users)
    finally:
        server.shutdown()
        thread.join(timeout=5)
