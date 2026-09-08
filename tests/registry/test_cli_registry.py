import socket
import threading

import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.passwords import UserStore
from hashpass.registry.remote import RemoteRegistry
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
    registry.users.add("dev", "s3cr3t", role="author")   # pushing images requires author role
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


@pytest.mark.tier1
def test_serve_checks_port_before_seeding_admin(tmp_path, monkeypatch):
    # a busy bind port must fail BEFORE any admin is created (no spurious admin/password)
    monkeypatch.delenv("HASHPASS_ADMIN_PASSWORD", raising=False)
    port = _free_port()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
        with pytest.raises(OSError):  # noqa: PT011  (bind failure: EADDRINUSE)
            cli.cmd_serve(env, host="127.0.0.1", port=port)
        assert UserStore(env.registry / "users.json").all_users() == []   # admin not seeded
    finally:
        blocker.close()


@pytest.mark.tier2
def test_login_failure_returns_1(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "wrong")
    assert cli.cmd_login(env, registry.base_url, "dev") == 1


@pytest.mark.tier2
def test_cmd_push_with_task_number_publishes_to_catalog(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t", role="author")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    store = ImageStore(env.images)
    _seed(store, tmp_path, "lab", (), "L")
    tdir = cli.task_dir("lab:1", store)              # make the image a task
    tdir.mkdir()
    (tdir / "task-meta.json").write_text('{"image_ref":"lab:1"}', encoding="utf-8")
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    assert cli.cmd_login(env, registry.base_url, "dev") == 0
    assert cli.cmd_push(env, "lab:1", registry.base_url, task_number=2, title="Lab") == 0
    client = RemoteRegistry(registry.base_url)
    cat = client.catalog(token=client.login("dev", "s3cr3t"))
    assert [(e["number"], e["ref"], e["title"]) for e in cat] == [(2, "lab:1", "Lab")]
