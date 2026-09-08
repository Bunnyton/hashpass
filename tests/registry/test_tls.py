"""Tier2: the pool can serve HTTPS (self-signed), and the client can talk to it."""
import secrets
import shutil
import subprocess
import threading

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry import remote as remote_mod
from hashpass.registry.passwords import UserStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.server import make_server


def _self_signed(tmp_path) -> tuple:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
        check=True, capture_output=True)
    return cert, key


@pytest.mark.tier2
@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_https_pool_round_trip(tmp_path, monkeypatch):
    cert, key = _self_signed(tmp_path)
    store = ImageStore(tmp_path / "srv")
    users = UserStore(tmp_path / "users.json")
    users.add("teacher", "pw", role="author")
    server = make_server(store, users, secrets.token_bytes(32), certfile=cert, keyfile=key)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("HASHPASS_TLS_INSECURE", "1")           # trust the self-signed cert
        monkeypatch.setattr(remote_mod, "_DIRECT", remote_mod._build_opener())  # noqa: SLF001
        client = RemoteRegistry(f"https://{host}:{port}")
        token = client.login("teacher", "pw")
        assert client.me(token=token)["user"] == "teacher"
    finally:
        server.shutdown()
        thread.join(timeout=5)
