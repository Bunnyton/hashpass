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
    registry.users.add("a", "pw", role="author")
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

    def fake_run(_env, _ref, _io, *, student_id, on_complete) -> int:  # noqa: ARG001
        on_complete(True)   # noqa: FBT003  (pretend every stage passed)
        return 0

    monkeypatch.setattr(cli, "cmd_run", fake_run)
    io = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "t")
    assert cli.cmd_pool_run(env, "1", io) == 0
    token = cli._pool_token(env, registry.base_url)  # noqa: SLF001
    prog = RemoteRegistry(registry.base_url).progress(token=token)
    assert prog["stud"]["lab:1"]["status"] == "passed"
