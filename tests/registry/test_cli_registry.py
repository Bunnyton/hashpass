import socket
import threading
import time

import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.creds import CredentialCache
from hashpass.registry.passwords import UserStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.server import make_server
from hashpass.registry.token import token_user


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
    registry.users.add("dev", "s3cr3t", role="admin")   # pushes an un-namespaced ref
    home = tmp_path / "home"
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    local = ImageStore(env.images)
    _seed(local, tmp_path, "base", (), "B")
    _seed(local, tmp_path, "lab", ("base:1",), "L")

    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0
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


@pytest.mark.tier1
def test_seed_admin_reset_uses_env_password(tmp_path, monkeypatch):
    monkeypatch.setenv("HASHPASS_ADMIN", "admin")
    monkeypatch.setenv("HASHPASS_ADMIN_PASSWORD", "envpw123")
    users = UserStore(tmp_path / "u.json")
    users.add("admin", "old", role="admin")
    io = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "")
    cli._seed_admin(users, io, reset=True)   # noqa: SLF001
    assert not users.verify("admin", "old")
    assert users.verify("admin", "envpw123")
    assert users.role("admin") == "admin"   # role preserved


@pytest.mark.tier1
def test_seed_admin_no_reset_skips_when_users_exist(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_ADMIN_PASSWORD", raising=False)
    users = UserStore(tmp_path / "u.json")
    users.add("admin", "keep", role="admin")
    io = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "")
    cli._seed_admin(users, io, reset=False)   # noqa: SLF001
    assert users.verify("admin", "keep")     # untouched


@pytest.mark.tier2
def test_login_failure_returns_1(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "wrong")
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 1


@pytest.mark.tier2
def test_cmd_push_with_task_number_publishes_to_catalog(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t", role="admin")   # pushes an un-namespaced ref
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    store = ImageStore(env.images)
    _seed(store, tmp_path, "lab", (), "L")
    tdir = cli.task_dir("lab:1", store)              # make the image a task
    tdir.mkdir()
    (tdir / "task-meta.json").write_text('{"image_ref":"lab:1"}', encoding="utf-8")
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0
    assert cli.cmd_push(env, "lab:1", registry.base_url, publish=True) == 0
    client = RemoteRegistry(registry.base_url)
    cat = client.catalog(token=client.login("dev", "s3cr3t"))
    assert [(e["number"], e["ref"]) for e in cat] == [(1, "lab:1")]   # auto-numbered


@pytest.mark.tier2
def test_pool_images_lists_stored_refs(registry, tmp_path):
    registry.users.add("dev", "s3cr3t", role="admin")   # pushes an un-namespaced ref
    c = RemoteRegistry(registry.base_url)
    tok = c.login("dev", "s3cr3t")
    local = ImageStore(tmp_path / "loc")
    _seed(local, tmp_path, "img", (), "I")
    c.push(local, "img:1", token=tok)
    rows = c.pool_images(token=tok)
    assert {r["ref"] for r in rows} == {"img:1"}
    assert rows[0]["kind"] == "image"


@pytest.mark.tier1
def test_looks_like_registry_url_accepts_urls_and_rejects_junk():
    """
    Reject argparse arg-slurp — a stray positional must not be treated as a registry URL.

    Regression for `hashengine push ref --task 1`, where the trailing `1` used to be parsed
    as the (optional) registry positional, miss the token cache, and trigger a password prompt.
    """
    ok = ("http://127.0.0.1:8080", "https://135.106.177.228:8080", "pool.example.com",
          "127.0.0.1:8080", "10.0.0.1:8080")
    for value in ok:
        assert cli._looks_like_registry_url(value), value        # noqa: SLF001
    for value in ("1", "task", "abcdef", ""):
        assert not cli._looks_like_registry_url(value), value    # noqa: SLF001


@pytest.mark.tier2
def test_cmd_push_rejects_junk_registry_before_prompting(registry, tmp_path, monkeypatch):
    """A junk positional (`push ref --task 1` → registry='1') must NOT reach the password prompt."""
    registry.users.add("dev", "s3cr3t", role="author")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    _seed(ImageStore(env.images), tmp_path, "img", (), "I")
    def _fail_getpass(_p: str = "") -> str:
        msg = "password prompt escaped junk-registry sanitizer"
        raise AssertionError(msg)
    monkeypatch.setattr("getpass.getpass", _fail_getpass)
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    with pytest.raises(RuntimeError, match="не похож на URL"):
        cli.cmd_push(env, "img:1", "1", io=io)


@pytest.mark.tier2
def test_cmd_push_prompts_login_when_no_token(registry, tmp_path, monkeypatch):
    # no cached token -> cmd_push logs in inline (io supplies the login) instead of erroring
    registry.users.add("dev", "s3cr3t", role="admin")   # pushes an un-namespaced ref
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    _seed(ImageStore(env.images), tmp_path, "img", (), "I")
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_push(env, "img:1", registry.base_url, io=io) == 0
    assert env.creds.exists()


@pytest.mark.tier2
def test_saved_registry_used_when_omitted(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    _seed(ImageStore(env.images), tmp_path, "img", (), "I")
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0     # saves the URL + token
    assert cli.cmd_push(env, "img:1") == 0                    # registry omitted -> uses the saved one


@pytest.mark.tier2
def test_cmd_push_of_others_namespace_raises_ownership_error(registry, tmp_path, monkeypatch):
    """A logged-in author pushing another author's namespaced ref gets a clear RuntimeError."""
    registry.users.add("dev", "s3cr3t", role="author")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    store = ImageStore(env.images)
    src = tmp_path / "src-app"
    src.mkdir()
    (src / "f.txt").write_text("X", encoding="utf-8")
    store.save("other/app", "1", src, ())
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    with pytest.raises(RuntimeError, match="принадлежит другому автору"):
        cli.cmd_push(env, "other/app:1", registry.base_url, io=io)


# -- logout / re-login -------------------------------------------------------

@pytest.mark.tier2
def test_cmd_login_declines_relogin_keeps_session(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io1 = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io1) == 0
    cache = CredentialCache(env.creds)
    before = cache.cached_token(registry.base_url, now=time.time())
    assert before is not None

    def _fail_getpass(_p: str = "") -> str:
        msg = "declining re-login must not re-prompt for a password"
        raise AssertionError(msg)
    monkeypatch.setattr("getpass.getpass", _fail_getpass)
    answers = iter(["n"])
    out: list[str] = []
    io2 = cli.Io(read=lambda _p: next(answers), write=out.append, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io2) == 0
    assert cache.cached_token(registry.base_url, now=time.time()) == before
    assert "остаёмся" in "".join(out)


@pytest.mark.tier2
def test_cmd_login_relogin_switches_user(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t", role="admin")
    registry.users.add("bob", "b0bpass!", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io1 = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io1) == 0

    monkeypatch.setattr("getpass.getpass", lambda _p="": "b0bpass!")
    answers = iter(["y", "bob"])
    io2 = cli.Io(read=lambda _p: next(answers), write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io2) == 0
    cache = CredentialCache(env.creds)
    token = cache.cached_token(registry.base_url, now=time.time())
    assert token_user(token) == "bob"
    assert cli.load_pool(env)["user"] == "bob"


@pytest.mark.tier2
def test_cmd_login_if_needed_skips_relogin_question(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io1 = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io1) == 0

    def _fail_read(_p: str = "") -> str:
        msg = "--if-needed must not prompt"
        raise AssertionError(msg)
    out: list[str] = []
    io2 = cli.Io(read=_fail_read, write=out.append, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io2, if_needed=True) == 0
    assert "уже вошли" in "".join(out)


@pytest.mark.tier2
def test_cmd_logout_forgets_token_keeps_url(registry, tmp_path, monkeypatch):
    registry.users.add("dev", "s3cr3t", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t")
    io = cli.Io(read=lambda _p: "dev", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0

    out: list[str] = []
    io2 = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    assert cli.cmd_logout(env, registry.base_url, io2) == 0
    cache = CredentialCache(env.creds)
    assert cache.cached_token(registry.base_url, now=time.time()) is None
    pool = cli.load_pool(env)
    assert pool["url"] == registry.base_url
    assert pool["user"] == ""
    assert "вышли" in "".join(out) and "dev" in "".join(out)

    out2: list[str] = []
    io3 = cli.Io(read=lambda _p: None, write=out2.append, clock=lambda: "")
    assert cli.cmd_logout(env, registry.base_url, io3) == 0
    assert "не было" in "".join(out2)


@pytest.mark.tier2
def test_cmd_logout_with_no_known_pool(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_POOL", raising=False)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    out: list[str] = []
    io = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    assert cli.cmd_logout(env, None, io) == 0
    assert "не задан" in "".join(out)


@pytest.mark.tier2
def test_cmd_pool_login_declines_relogin_keeps_session(registry, tmp_path, monkeypatch):
    registry.users.add("stud", "pass123!", role="student")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "pass123!")
    io1 = cli.Io(read=lambda _p: "stud", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_pool_login(env, registry.base_url, io1) == 0

    def _fail_getpass(_p: str = "") -> str:
        msg = "declining re-login must not re-prompt for a password"
        raise AssertionError(msg)
    monkeypatch.setattr("getpass.getpass", _fail_getpass)
    answers = iter(["n"])
    out: list[str] = []
    io2 = cli.Io(read=lambda _p: next(answers), write=out.append, clock=lambda: "")
    assert cli.cmd_pool_login(env, registry.base_url, io2) == 0
    assert "остаёмся" in "".join(out)


@pytest.mark.tier2
def test_cmd_logout_forgets_token_under_every_url_spelling(registry, tmp_path):
    """A token cached under a different spelling of the same pool URL must not survive logout."""
    registry.users.add("dev", "s3cr3t", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    bare = registry.base_url.removeprefix("http://")           # e.g. pool.json without a scheme
    token = RemoteRegistry(registry.base_url).login("dev", "s3cr3t")
    CredentialCache(env.creds).save(bare, token, int(time.time()) + 3600)

    out: list[str] = []
    io = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    assert cli.cmd_logout(env, registry.base_url, io) == 0
    assert "вышли" in "".join(out) and "dev" in "".join(out)
    assert cli._pool_token(env, bare) is None                   # noqa: SLF001 -- the variant is gone too


@pytest.mark.tier2
def test_cmd_login_relogin_forgets_old_token_under_every_url_spelling(registry, tmp_path, monkeypatch):
    """Accepting re-login must drop the old token even when it was cached under a variant spelling."""
    registry.users.add("dev", "s3cr3t", role="admin")
    registry.users.add("bob", "b0bpass!", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    bare = registry.base_url.removeprefix("http://")
    token = RemoteRegistry(registry.base_url).login("dev", "s3cr3t")
    CredentialCache(env.creds).save(bare, token, int(time.time()) + 3600)

    monkeypatch.setattr("getpass.getpass", lambda _p="": "b0bpass!")
    answers = iter(["y", "bob"])
    io = cli.Io(read=lambda _p: next(answers), write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0
    # the old "dev" token must be gone under EVERY spelling -- looking it up via either the
    # bare or the full URL now resolves to the new session, never to the stale "dev" one.
    assert token_user(cli._pool_token(env, bare)) == "bob"                     # noqa: SLF001
    assert token_user(cli._pool_token(env, registry.base_url)) == "bob"        # noqa: SLF001


@pytest.mark.tier2
def test_cache_hit_or_forget_purges_ghost_token_under_every_url_spelling(registry, tmp_path):
    """A deleted account's ghost token must be dropped under every cached spelling, not just one."""
    registry.users.add("dev", "s3cr3t", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    bare = registry.base_url.removeprefix("http://")           # token cached under a variant...
    token = RemoteRegistry(registry.base_url).login("dev", "s3cr3t")
    CredentialCache(env.creds).save(bare, token, int(time.time()) + 3600)
    registry.users.delete("dev")                                # ...but the account is now gone

    out: list[str] = []
    io = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    # called with the FULL url (not the bare spelling the token actually lives under)
    assert cli._cache_hit_or_forget(env, registry.base_url, io) is None        # noqa: SLF001
    assert cli._pool_token(env, bare) is None                                  # noqa: SLF001


@pytest.mark.tier2
def test_require_pool_identity_purges_ghost_token_under_every_url_spelling(registry, tmp_path, monkeypatch):
    """Same ghost-account cleanup, exercised via _require_pool_identity's own forget call."""
    registry.users.add("dev", "s3cr3t", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    bare = registry.base_url.removeprefix("http://")
    token = RemoteRegistry(registry.base_url).login("dev", "s3cr3t")
    CredentialCache(env.creds).save(bare, token, int(time.time()) + 3600)
    cli.save_pool(env, registry.base_url, "dev")
    registry.users.delete("dev")

    monkeypatch.setenv("HASHPASS_POOL", registry.base_url)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "newpass123!")

    def _read(prompt: str) -> str:
        return "dev2" if "логин" in prompt else ""      # group/comment left blank
    io = cli.Io(read=_read, write=lambda _s: None, clock=lambda: "")
    cli._require_pool_identity(env, io)                                       # noqa: SLF001
    # the old "dev" ghost token must be gone under every spelling -- the bare spelling now
    # resolves to the freshly registered "dev2" session, never to the stale "dev" one.
    assert token_user(cli._pool_token(env, bare)) == "dev2"                    # noqa: SLF001
