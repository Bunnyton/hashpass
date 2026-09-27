"""Tier2: `hashengine push base` -- a fixed tag that is re-pushed only when the local base changed."""
from pathlib import Path

import pytest

from hashpass import cli
from hashpass.image.base import runtime_stamp
from hashpass.imagestore.store import ImageStore
from hashpass.registry.remote import RemoteRegistry


def _seed_base(store: ImageStore, tmp_path: Path, marker: str) -> str:
    """Store a fake base under base_ref() the way a local build does (meta.json rewritten)."""
    src = tmp_path / f"src-{marker}"
    (src / "etc").mkdir(parents=True)
    (src / "etc" / "hp-base-version").write_text(runtime_stamp() + "\n", encoding="utf-8")
    (src / "marker.txt").write_text(marker, encoding="utf-8")
    name, version = cli.base_ref().split(":")
    store.save(name, version, src, ())
    return cli.base_ref()


@pytest.fixture
def author_env(registry, tmp_path, monkeypatch) -> cli.Home:
    """Log in as `bunnyton` (the base OWNER, deliberately not an admin); the base is seeded per test."""
    registry.users.add("bunnyton", "pw-correct", role="author")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "pw-correct")
    io = cli.Io(read=lambda _p: "bunnyton", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0
    # cmd_push_base first ensures the base locally (a 2-minute apt build): the tests seed it.
    monkeypatch.setattr(cli, "ensure_base_image",
                        lambda _env, store, **_kw: store.get(cli.base_ref()).layer)
    return env


def _io(out: list[str]) -> cli.Io:
    return cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")


@pytest.mark.tier2
def test_push_base_uploads_when_the_pool_lacks_it_then_skips_while_unchanged(registry, author_env, tmp_path):
    store = ImageStore(author_env.images)
    ref = _seed_base(store, tmp_path, "v1")
    remote = RemoteRegistry(registry.base_url)
    out: list[str] = []
    assert cli.cmd_push_base(author_env, registry.base_url, io=_io(out)) == 0
    first = remote.image_digest(ref)
    assert first and store.get(ref).pool_digest == first
    assert cli.cmd_push_base(author_env, registry.base_url, io=_io(out)) == 0
    assert remote.image_digest(ref) == first                       # NOT re-uploaded
    assert any("актуальна" in s for s in out)


@pytest.mark.tier2
def test_push_base_reuploads_a_locally_rebuilt_base(registry, author_env, tmp_path):
    store = ImageStore(author_env.images)
    ref = _seed_base(store, tmp_path, "v1")
    remote = RemoteRegistry(registry.base_url)
    assert cli.cmd_push_base(author_env, registry.base_url, io=_io([])) == 0
    first = remote.image_digest(ref)
    _seed_base(store, tmp_path, "v2")          # a rebuild rewrites meta.json: pool_digest is gone
    assert store.get(ref).pool_digest is None
    assert cli.cmd_push_base(author_env, registry.base_url, io=_io([])) == 0
    second = remote.image_digest(ref)
    assert second != first
    assert store.get(ref).pool_digest == second


@pytest.mark.tier2
def test_push_base_keeps_a_base_pushed_from_another_machine_unless_forced(registry, author_env, tmp_path):
    store = ImageStore(author_env.images)
    ref = _seed_base(store, tmp_path, "v1")
    remote = RemoteRegistry(registry.base_url)
    assert cli.cmd_push_base(author_env, registry.base_url, io=_io([])) == 0
    other = ImageStore(tmp_path / "other")                         # another admin machine
    _seed_base(other, tmp_path, "v9")
    theirs_client = RemoteRegistry(registry.base_url)
    token = theirs_client.login("bunnyton", "pw-correct")
    theirs_client.push(other, ref, token=token, force=True)
    theirs = remote.image_digest(ref)
    out: list[str] = []
    assert cli.cmd_push_base(author_env, registry.base_url, io=_io(out)) == 0
    assert remote.image_digest(ref) == theirs                      # untouched without --force
    assert any("другой машины" in s for s in out)
    assert cli.cmd_push_base(author_env, registry.base_url, force=True, io=_io([])) == 0
    assert remote.image_digest(ref) != theirs
