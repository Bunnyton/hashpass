"""Tier2: /submit (digest-gated, principal-bound) + /progress over the live server."""
import urllib.error
from http import HTTPStatus

import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest


def _make_task_dir(root) -> None:
    (root / "bundle").mkdir(parents=True)
    (root / "bundle" / "c.json").write_text('{"s":[]}', encoding="utf-8")
    (root / "task-meta.json").write_text('{"image_ref":"lab:1"}', encoding="utf-8")


def _seed_image(store, tmp_path, name) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, "1", src, ())


def _publish(registry, tmp_path) -> tuple:
    """Publish author task #1 (lab:1); return (task_dir, author_token)."""
    registry.users.add("a", "pw", role="admin")   # pushes an un-namespaced ref
    ac = RemoteRegistry(registry.base_url)
    atok = ac.login("a", "pw")
    local = ImageStore(tmp_path / "local")
    _seed_image(local, tmp_path, "lab")
    ac.push(local, "lab:1", token=atok)
    td = tmp_path / "task"
    td.mkdir()
    _make_task_dir(td)
    ac.push_task(td, "lab", "1", publish=True, token=atok)
    return td, atok


@pytest.mark.tier2
def test_submit_passed_records_progress_and_key(registry, tmp_path):
    td, _ = _publish(registry, tmp_path)
    sc = RemoteRegistry(registry.base_url)
    stok = sc.register("stud", "pass123!", group="G")
    result = sc.submit("lab:1", task_digest(td), passed=True, token=stok)
    assert result["status"] == "passed"
    assert str(result["global_key"]).startswith("gkey{")
    assert sc.progress(token=stok)["stud"]["lab:1"]["status"] == "passed"


@pytest.mark.tier2
def test_submit_digest_mismatch_fails_without_key(registry, tmp_path):
    _publish(registry, tmp_path)
    sc = RemoteRegistry(registry.base_url)
    stok = sc.register("stud", "pass123!", group="G")
    result = sc.submit("lab:1", "deadbeef", passed=True, token=stok)
    assert result["status"] == "failed"
    assert result.get("reason") == "digest-mismatch"
    assert "global_key" not in result
    assert sc.progress(token=stok)["stud"]["lab:1"]["status"] == "failed"


@pytest.mark.tier2
def test_submit_unknown_task_is_404(registry):
    sc = RemoteRegistry(registry.base_url)
    stok = sc.register("stud", "pass123!", group="G")
    with pytest.raises(urllib.error.HTTPError) as exc:
        sc.submit("ghost:1", "d", passed=True, token=stok)
    assert exc.value.code == HTTPStatus.NOT_FOUND


@pytest.mark.tier2
def test_progress_author_sees_all_student_sees_self(registry, tmp_path):
    td, atok = _publish(registry, tmp_path)
    s1 = RemoteRegistry(registry.base_url)
    t1 = s1.register("s1", "pass123!", group="G")
    s2 = RemoteRegistry(registry.base_url)
    t2 = s2.register("s2", "pass123!", group="G")
    s1.submit("lab:1", task_digest(td), passed=True, token=t1)
    s2.submit("lab:1", task_digest(td), passed=True, token=t2)
    assert set(s1.progress(token=t1)) == {"s1"}                 # student: only self
    assert {"s1", "s2"} <= set(RemoteRegistry(registry.base_url).progress(token=atok))  # author: all


@pytest.mark.tier2
def test_register_rejects_unsafe_username(registry):
    sc = RemoteRegistry(registry.base_url)
    with pytest.raises(urllib.error.HTTPError) as exc:
        sc.register("../evil", "pass123!", group="G")
    assert exc.value.code == HTTPStatus.BAD_REQUEST


@pytest.mark.tier2
def test_cmd_pool_run_submits_on_completion(registry, tmp_path, monkeypatch):
    # Wire the student run->submit path without a real container: stub cmd_run to fire
    # on_complete(True), and assert the pool recorded the pass under the student's identity.
    monkeypatch.setenv("HASHPASS_POOL", registry.base_url)
    _publish(registry, tmp_path)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "stud")}, default_home=tmp_path)
    RemoteRegistry(registry.base_url, cache=CredentialCache(env.creds)).register(
        "stud", "pass123!", group="G")

    pulls: list[tuple[list[str], bool]] = []
    orig = RemoteRegistry.pull_many

    def spy_pull_many(self, refs, store, *, workers=8, refresh=False) -> list[str]:
        pulls.append((list(refs), refresh))
        return orig(self, refs, store, workers=workers, refresh=refresh)

    monkeypatch.setattr(RemoteRegistry, "pull_many", spy_pull_many)

    def fake_run(_env, _ref, _io, *, student_id, on_complete, pool=None) -> int:  # noqa: ARG001
        on_complete(True, [])   # noqa: FBT003  (pretend every stage passed; no history)
        return 0

    monkeypatch.setattr(cli, "cmd_run", fake_run)
    io = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "t")
    assert cli.cmd_pool_run(env, "1", io) == 0
    token = cli._pool_token(env, registry.base_url)  # noqa: SLF001
    prog = RemoteRegistry(registry.base_url).progress(token=token)
    assert prog["stud"]["lab:1"]["status"] == "passed"
    # cmd_pool_run refreshes the TASK ref only (by digest); the base is ensure_base_image's job.
    assert pulls == [(["lab:1"], True)]


def _push_fake_base(registry, tmp_path, marker: str) -> str:
    """Push a tiny 'base' under the CURRENT stamped ref (mirrors tests/registry/test_base_pull.py)."""
    registry.users.add(f"baseauthor-{marker}", "pw-correct", role="admin")   # only admins push the base
    local = ImageStore(tmp_path / f"base-local-{marker}")
    src = tmp_path / f"base-src-{marker}"
    src.mkdir()
    (src / "marker.txt").write_text(marker, encoding="utf-8")
    name, version = cli.base_ref().split(":")
    local.save(name, version, src, ())
    client = RemoteRegistry(registry.base_url, cache=CredentialCache(tmp_path / f"base-c-{marker}.json"))
    client.login(f"baseauthor-{marker}", "pw-correct")
    client.push(local, cli.base_ref(), force=True)
    return cli.base_ref()


def _student_env(registry, tmp_path, monkeypatch, who: str):  # noqa: ANN202
    monkeypatch.setenv("HASHPASS_POOL", registry.base_url)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / who)}, default_home=tmp_path)
    RemoteRegistry(registry.base_url, cache=CredentialCache(env.creds)).register(
        who, "pass123!", group="G")
    return env


def _stub_cmd_run(monkeypatch) -> list[str]:
    ran: list[str] = []

    def fake_run(_env, ref, _io, *, student_id, on_complete, pool=None) -> int:  # noqa: ARG001
        ran.append(ref)
        on_complete(True, [])   # noqa: FBT003
        return 0

    monkeypatch.setattr(cli, "cmd_run", fake_run)
    return ran


@pytest.mark.tier2
def test_cmd_pool_run_pulls_only_the_task_even_when_pool_has_a_base(registry, tmp_path, monkeypatch):
    # The base is fetched/refreshed by ensure_base_image(pool=client) inside _run_task, which
    # degrades to a good local base on a torn/failed download; cmd_pool_run must not pull it.
    _publish(registry, tmp_path)
    _push_fake_base(registry, tmp_path, "v1")
    env = _student_env(registry, tmp_path, monkeypatch, "stud2")
    pulls: list[tuple[list[str], bool]] = []
    orig = RemoteRegistry.pull_many

    def spy_pull_many(self, refs, store, *, workers=8, refresh=False) -> list[str]:
        pulls.append((list(refs), refresh))
        return orig(self, refs, store, workers=workers, refresh=refresh)

    monkeypatch.setattr(RemoteRegistry, "pull_many", spy_pull_many)
    ran = _stub_cmd_run(monkeypatch)
    io = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "t")
    assert cli.cmd_pool_run(env, "1", io) == 0
    assert pulls == [(["lab:1"], True)] and ran == ["lab:1"]


@pytest.mark.tier2
def test_cmd_pool_run_survives_failing_base_download_with_local_base(registry, tmp_path, monkeypatch):
    _publish(registry, tmp_path)
    _push_fake_base(registry, tmp_path, "v1")
    env = _student_env(registry, tmp_path, monkeypatch, "stud3")
    # A good local base exists, but it is digest-stale vs the pool (so a refresh WOULD fetch it).
    local = ImageStore(env.images)
    src = tmp_path / "local-base"
    src.mkdir()
    (src / "marker.txt").write_text("local", encoding="utf-8")
    name, version = cli.base_ref().split(":")
    local.save(name, version, src, ())
    local.set_pool_digest(cli.base_ref(), "0" * 64)
    orig_download = RemoteRegistry.download_image

    def failing_download(self, ref, dest, **kw):  # noqa: ANN202, ANN003
        if ref == cli.base_ref():
            msg = f"digest mismatch for {ref}: torn"
            raise ValueError(msg)
        return orig_download(self, ref, dest, **kw)

    monkeypatch.setattr(RemoteRegistry, "download_image", failing_download)
    ran = _stub_cmd_run(monkeypatch)
    io = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "t")
    assert cli.cmd_pool_run(env, "1", io) == 0                      # no raise
    assert ran == ["lab:1"]
    assert (local.get(cli.base_ref()).layer / "marker.txt").read_text(encoding="utf-8") == "local"
    # and the base path itself degrades to that local base instead of raising
    client = RemoteRegistry(registry.base_url)
    assert cli.ensure_base_image(env, local, pool=client, io=io) == local.get(cli.base_ref()).layer
