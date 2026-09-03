import socket
import threading

import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.passwords import UserStore
from hashpass.registry.server import make_server


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.tier2
def test_require_login_prompts_once_then_caches(tmp_path, monkeypatch):
    # Login for image creation: asked once (prompt + auto-register + token cache), then reused
    # silently. A second prompt would exhaust the one-item answers iterator and raise.
    port = _free_port()
    monkeypatch.setenv("HASHPASS_REGISTRY", f"http://127.0.0.1:{port}")
    monkeypatch.setattr("getpass.getpass", lambda _p="": "pw")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    # Start the very service the autostart would, sharing env.registry's store/users/secret.
    server = make_server(
        ImageStore(env.registry / "store"),
        UserStore(env.registry / "users.json"),
        cli._registry_secret(env), host="127.0.0.1", port=port,  # noqa: SLF001
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        answers = iter(["dev"])
        io = cli.Io(read=lambda _p: next(answers), write=lambda _s: None, clock=lambda: "")
        assert cli._require_login(env, io) == "dev"      # prompt + register + login + cache  # noqa: SLF001
        assert cli._require_login(env, io) == "dev"      # cached: no second prompt  # noqa: SLF001
        assert env.creds.exists()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _seed(store, tmp_path, name, parents, marker) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / f"{name}.txt").write_text(marker, encoding="utf-8")
    store.save(name, "1", src, parents)


@pytest.mark.tier2
def test_login_push_pull_through_localhost(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t")
    home = tmp_path / "home"
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    local = ImageStore(env.images)
    _seed(local, tmp_path, "base", (), "B")
    _seed(local, tmp_path, "lab", ("base:1",), "L")

    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    assert cli.cmd_login(env, registry.base_url, "dev") == 0
    assert env.creds.exists()                       # token cached

    assert cli.cmd_push(env, "lab:1", registry.base_url) == 0

    dest_home = tmp_path / "dest"
    dest_env = cli.build_env({"HASHPASS_HOME": str(dest_home)}, default_home=tmp_path)
    assert cli.cmd_pull(dest_env, "lab:1", registry.base_url) == 0
    assert ImageStore(dest_env.images).list() == ["base:1", "lab:1"]


@pytest.mark.tier2
def test_login_failure_returns_1(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "wrong")
    assert cli.cmd_login(env, registry.base_url, "dev") == 1
