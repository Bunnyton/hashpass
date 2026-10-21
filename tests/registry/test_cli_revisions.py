"""Tier2: `hashengine tag | rm | fork | run` against a live localhost pool (spec 2026-10-21 §2, §10)."""
import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.revisions import RepoIndex


def _seed(store: ImageStore, tmp_path, name: str, marker: str, parents: tuple[str, ...] = ()) -> None:
    src = tmp_path / f"src-{name.replace('/', '-')}"
    src.mkdir(exist_ok=True)
    (src / "marker.txt").write_text(marker, encoding="utf-8")
    store.save(name, "1", src, parents)


def _login(registry, tmp_path, monkeypatch, user: str, home: str) -> cli.Home:
    registry.users.add(user, "s3cr3t-pw1", role="author")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / home)}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "s3cr3t-pw1")
    io = cli.Io(read=lambda _p: user, write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0
    monkeypatch.setenv("HASHPASS_POOL", registry.base_url)
    return env


@pytest.mark.tier2
def test_tag_then_remove_a_revision(registry, tmp_path, monkeypatch, capsys):
    env = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    local = ImageStore(env.images)
    _seed(local, tmp_path, "bob/lab", "one")
    assert cli.cmd_push(env, "bob/lab:1", registry.base_url) == 0
    _seed(local, tmp_path, "bob/lab", "two")
    assert cli.cmd_push(env, "bob/lab:1", registry.base_url) == 0
    assert "отправлено bob/lab:1_v2" in capsys.readouterr().out
    assert cli.cmd_tag(env, "bob/lab:1_v1", "stable", registry.base_url) == 0
    assert registry.store.exists("bob/lab:stable_v1")
    assert cli.cmd_rm(env, "bob/lab:1_v2", registry.base_url) == 0
    assert not registry.store.exists("bob/lab:1_v2")
    with pytest.raises(ValueError, match="_vN"):
        cli.cmd_rm(env, "bob/lab:1", registry.base_url)          # a tag is not a revision


@pytest.mark.tier2
def test_unchanged_push_says_so(registry, tmp_path, monkeypatch, capsys):
    env = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    _seed(ImageStore(env.images), tmp_path, "bob/lab", "one")
    cli.cmd_push(env, "bob/lab:1", registry.base_url)
    capsys.readouterr()
    cli.cmd_push(env, "bob/lab:1", registry.base_url)
    assert "без изменений: bob/lab:1_v1" in capsys.readouterr().out


@pytest.mark.tier2
def test_push_refuses_a_reserved_tag(registry, tmp_path, monkeypatch):
    env = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    store = ImageStore(env.images)
    src = tmp_path / "s"
    src.mkdir()
    store.save("bob/lab", "1_v2", src, ())
    with pytest.raises(ValueError, match="зарезервирован"):
        cli.cmd_push(env, "bob/lab:1_v2", registry.base_url)


@pytest.mark.tier2
def test_fork_into_your_namespace(registry, tmp_path, monkeypatch):
    bob = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    _seed(ImageStore(bob.images), tmp_path, "bob/lab", "one")
    cli.cmd_push(bob, "bob/lab:1", registry.base_url)
    eve = _login(registry, tmp_path, monkeypatch, "eve", "eve")
    assert cli.cmd_fork(eve, "bob/lab:1", None, registry.base_url) == 0
    assert registry.store.exists("eve/lab:1_v1")
    assert RepoIndex(registry.store.root / ".repos", "eve/lab").fork_of == "bob/lab:1_v1"


@pytest.mark.tier2
def test_local_rm_drops_an_alias_or_a_build(registry, tmp_path, monkeypatch):
    env = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    store = ImageStore(env.images)
    _seed(store, tmp_path, "bob/lab", "one")
    assert cli.cmd_rm(env, "bob/lab:1", local=True) == 0
    assert not store.exists("bob/lab:1")


@pytest.mark.tier2
def test_engine_run_pulls_a_missing_ref_first(registry, tmp_path, monkeypatch):
    bob = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    _seed(ImageStore(bob.images), tmp_path, "bob/lab", "one")
    cli.cmd_push(bob, "bob/lab:1", registry.base_url)
    other = _login(registry, tmp_path, monkeypatch, "eve", "eve")
    ran: list[str] = []
    monkeypatch.setattr(cli, "cmd_run", lambda _env, ref, _io=None, **_k: ran.append(ref) or 0)
    assert cli.cmd_engine_run(other, "bob/lab:1", registry.base_url) == 0
    assert ran == ["bob/lab:1"]
    assert ImageStore(other.images).get("bob/lab:1").version == "1_v1"
