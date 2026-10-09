"""Tier2: the base image is pulled from the pool under its fixed tag instead of being built."""
from pathlib import Path

import pytest

from hashpass import cli
from hashpass.image.base import runtime_stamp
from hashpass.imagestore.store import ImageStore
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry


def _push_fake_base(registry, tmp_path: Path, marker: str) -> str:
    """Push a tiny 'base' under the CURRENT stamped ref (a real base is a 130 MB tier3 thing)."""
    registry.users.add("author", "pw-correct", role="admin")   # only admins push the base
    local = ImageStore(tmp_path / f"local-{marker}")
    src = tmp_path / f"src-{marker}"
    (src / "etc").mkdir(parents=True)
    (src / "etc" / "hp-base-version").write_text(runtime_stamp() + "\n", encoding="utf-8")
    (src / "marker.txt").write_text(marker, encoding="utf-8")
    name, version = cli.base_ref().split(":")
    local.save(name, version, src, ())
    client = RemoteRegistry(registry.base_url, cache=CredentialCache(tmp_path / f"c-{marker}.json"))
    client.login("author", "pw-correct")
    client.push(local, cli.base_ref(), force=True)
    return cli.base_ref()


def _env(tmp_path: Path) -> cli.Home:
    return cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)


@pytest.mark.tier1
def test_base_ref_is_a_fixed_owner_namespaced_tag():
    # Docker-like: the base is ONE image with a fixed tag, owned by its author; an updated
    # base is re-pushed under the same tag and reaches students by digest, never by a new ref.
    assert cli.base_ref() == "bunnyton/debian:trixie"
    assert runtime_stamp().isdigit()          # the stamp still marks a locally built base


@pytest.mark.tier2
def test_ensure_base_pulls_from_pool_and_only_repulls_when_digest_changes(registry, tmp_path, monkeypatch):
    ref = _push_fake_base(registry, tmp_path, "v1")
    monkeypatch.setattr(cli, "build_base", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("built locally")))
    env = _env(tmp_path)
    store = ImageStore(env.images)
    pool = RemoteRegistry(registry.base_url)
    layer = cli.ensure_base_image(env, store, pool=pool)
    assert (layer / "marker.txt").read_text(encoding="utf-8") == "v1"
    assert store.get(ref).pool_digest == pool.image_digest(ref)
    downloads: list[str] = []
    monkeypatch.setattr(RemoteRegistry, "download_image",
                        lambda self, r, d, _orig=RemoteRegistry.download_image, **kw: downloads.append(r) or _orig(self, r, d, **kw))
    assert cli.ensure_base_image(env, store, pool=pool) == layer          # same digest: no download
    assert downloads == []
    _push_fake_base(registry, tmp_path, "v2")                             # author re-pushed the base
    assert (cli.ensure_base_image(env, store, pool=pool) / "marker.txt").read_text(encoding="utf-8") == "v2"
    assert downloads == [ref]


@pytest.mark.tier2
def test_ensure_base_pulls_legacy_base_once(registry, tmp_path, monkeypatch):
    # A base uploaded by a pre-digest server: served without X-Image-Digest. Pull it once,
    # then never hit the network for it again (no digest -> can't be stale).
    monkeypatch.setattr(cli, "build_base", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("built locally")))
    name, version = cli.base_ref().split(":")
    src = tmp_path / "legacy-src"
    src.mkdir()
    (src / "marker.txt").write_text("legacy", encoding="utf-8")
    registry.store.save(name, version, src, ())                           # layer/-only on the server
    env = _env(tmp_path)
    store = ImageStore(env.images)
    pool = RemoteRegistry(registry.base_url)
    layer = cli.ensure_base_image(env, store, pool=pool)
    assert (layer / "marker.txt").read_text(encoding="utf-8") == "legacy"
    calls: list[str] = []
    monkeypatch.setattr(RemoteRegistry, "download_image", lambda _self, r, _d, **_kw: calls.append(r))
    assert cli.ensure_base_image(env, store, pool=pool) == layer
    assert calls == []


@pytest.mark.tier2
def test_ensure_base_falls_back_to_local_build_when_pool_lacks_it(registry, tmp_path, monkeypatch):
    built: list[Path] = []

    def fake_build(dest: Path, *, from_tar: Path) -> Path:  # noqa: ARG001
        (dest / "etc").mkdir(parents=True, exist_ok=True)
        (dest / "etc" / "hp-base-version").write_text(runtime_stamp() + "\n", encoding="utf-8")
        built.append(dest)
        return dest

    monkeypatch.setattr(cli, "build_base", fake_build)
    monkeypatch.setattr(cli, "ensure_base_tar", lambda p: p)
    env = _env(tmp_path)
    store = ImageStore(env.images)
    out: list[str] = []
    io = cli.Io(read=lambda _p="": "", write=out.append, clock=lambda: "t")
    layer = cli.ensure_base_image(env, store, pool=RemoteRegistry(registry.base_url), io=io)
    assert built and store.exists(cli.base_ref()) and layer == store.get(cli.base_ref()).layer
    assert any("на пуле не найдена" in s for s in out)


@pytest.mark.tier2
def test_ensure_base_reuses_local_base_when_pool_unreachable(registry, tmp_path, monkeypatch):
    # A pool that is merely down must not crash a run when a perfectly good base is already
    # local -- reuse it silently instead of propagating the connection error.
    ref = _push_fake_base(registry, tmp_path, "v1")
    env = _env(tmp_path)
    store = ImageStore(env.images)
    pool = RemoteRegistry(registry.base_url)
    layer = cli.ensure_base_image(env, store, pool=pool)          # first pull: pool is up
    assert store.exists(ref)
    monkeypatch.setattr(RemoteRegistry, "image_digest",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("не удалось подключиться")))
    monkeypatch.setattr(cli, "build_base", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("built locally")))
    assert cli.ensure_base_image(env, store, pool=pool) == layer   # pool down now: reuse local, no raise


@pytest.mark.tier2
def test_ensure_base_builds_locally_when_pool_unreachable_and_nothing_local(tmp_path, monkeypatch):
    built: list[Path] = []

    def fake_build(dest: Path, *, from_tar: Path) -> Path:  # noqa: ARG001
        (dest / "etc").mkdir(parents=True, exist_ok=True)
        (dest / "etc" / "hp-base-version").write_text(runtime_stamp() + "\n", encoding="utf-8")
        built.append(dest)
        return dest

    monkeypatch.setattr(cli, "build_base", fake_build)
    monkeypatch.setattr(cli, "ensure_base_tar", lambda p: p)
    monkeypatch.setattr(RemoteRegistry, "image_digest",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("не удалось подключиться")))
    env = _env(tmp_path)
    store = ImageStore(env.images)
    out: list[str] = []
    io = cli.Io(read=lambda _p="": "", write=out.append, clock=lambda: "t")
    layer = cli.ensure_base_image(env, store, pool=RemoteRegistry("http://127.0.0.1:1"), io=io)
    assert built and store.exists(cli.base_ref()) and layer == store.get(cli.base_ref()).layer
    assert any("пул недоступен" in s for s in out)


def _push_fake_ref(registry, tmp_path: Path, ref: str, marker: str) -> None:
    """Push a tiny fake base under an arbitrary ref (an admin pushes it)."""
    if not registry.users.has("author"):
        registry.users.add("author", "pw-correct", role="admin")
    local = ImageStore(tmp_path / f"local-{marker}")
    src = tmp_path / f"src-{marker}"
    (src / "etc").mkdir(parents=True)
    (src / "etc" / "hp-base-version").write_text(runtime_stamp() + "\n", encoding="utf-8")
    (src / "marker.txt").write_text(marker, encoding="utf-8")
    name, version = ref.split(":")
    local.save(name, version, src, ())
    client = RemoteRegistry(registry.base_url, cache=CredentialCache(tmp_path / f"c-{marker}.json"))
    client.login("author", "pw-correct")
    client.push(local, ref, force=True)


@pytest.mark.tier2
def test_ensure_base_falls_back_to_the_legacy_stamped_ref_on_the_pool(registry, tmp_path, monkeypatch):
    # Cutover: the pool is not yet re-deployed and holds only the old `debian:trixie-<stamp>`.
    # A new client must pull THAT, not "build locally" (students have no rootfs tarball).
    monkeypatch.setattr(cli, "build_base", lambda *_a, **_k: pytest.fail("must not build"))
    legacy = f"debian:trixie-{runtime_stamp()}"
    _push_fake_ref(registry, tmp_path, legacy, "legacy")
    env = _env(tmp_path)
    store = ImageStore(env.images)
    out: list[str] = []
    io = cli.Io(read=lambda _p="": "", write=out.append, clock=lambda: "t")
    layer = cli.ensure_base_image(env, store, pool=RemoteRegistry(registry.base_url), io=io)
    assert layer == store.get(legacy).layer
    assert (layer / "marker.txt").read_text(encoding="utf-8") == "legacy"
    assert not store.exists(cli.base_ref())
    assert not any("собираю локально" in s for s in out)


@pytest.mark.tier2
def test_ensure_base_uses_a_current_local_legacy_base_when_the_pool_has_neither(registry, tmp_path, monkeypatch):
    # A student who already has the old stamped base locally keeps working after the client
    # update even while the pool has no base at all under either name.
    monkeypatch.setattr(cli, "build_base", lambda *_a, **_k: pytest.fail("must not build"))
    legacy = f"debian:trixie-{runtime_stamp()}"
    env = _env(tmp_path)
    store = ImageStore(env.images)
    src = tmp_path / "src-local-legacy"
    (src / "etc").mkdir(parents=True)
    (src / "etc" / "hp-base-version").write_text(runtime_stamp() + "\n", encoding="utf-8")
    name, version = legacy.split(":")
    store.save(name, version, src, ())
    io = cli.Io(read=lambda _p="": "", write=lambda _s: None, clock=lambda: "t")
    layer = cli.ensure_base_image(env, store, pool=RemoteRegistry(registry.base_url), io=io)
    assert layer == store.get(legacy).layer
