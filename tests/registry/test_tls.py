"""Tier2: an HTTPS pool with a self-signed cert is reached automatically (no env, scheme optional)."""
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.passwords import UserStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.server import make_server


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _self_signed(tmp_path: Path) -> tuple[Path, Path]:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(   # a throwaway self-signed cert for the test
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
        check=True, capture_output=True)
    return cert, key


@pytest.mark.tier2
@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_self_signed_https_pool_is_used_automatically(tmp_path, monkeypatch):
    # No TLS env vars: the client must trust the self-signed cert on its own, and figure out
    # the scheme so a bare host:port (and even a wrong http://) still reaches the HTTPS pool.
    monkeypatch.delenv("HASHPASS_TLS_INSECURE", raising=False)
    monkeypatch.delenv("HASHPASS_TLS_CAFILE", raising=False)
    cert, key = _self_signed(tmp_path)
    port = _free_port()
    users = UserStore(tmp_path / "users.json")
    users.add("admin", "pass123!", role="admin")
    server = make_server(ImageStore(tmp_path / "store"), users, b"0" * 32,
                         host="127.0.0.1", port=port, certfile=cert, keyfile=key)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert RemoteRegistry(f"https://127.0.0.1:{port}").login("admin", "pass123!")  # explicit https
        assert RemoteRegistry(f"127.0.0.1:{port}").login("admin", "pass123!")          # no scheme -> https
        assert RemoteRegistry(f"http://127.0.0.1:{port}").login("admin", "pass123!")   # http -> https fallback
    finally:
        server.shutdown()
        thread.join(timeout=5)
