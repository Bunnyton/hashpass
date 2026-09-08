"""Student pool client: pool.json config, URL resolution, number->ref, and parallel pull_new."""
import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry


class _FakeClient:
    def __init__(self, entries) -> None:
        self._entries = entries

    def catalog(self, *, token) -> list:  # noqa: ARG002
        return self._entries


@pytest.mark.tier1
def test_pool_config_roundtrip(tmp_path):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "h")}, default_home=tmp_path)
    assert cli.load_pool(env) == {}
    cli.save_pool(env, "http://pool", "alice")
    assert cli.load_pool(env) == {"url": "http://pool", "user": "alice"}


@pytest.mark.tier1
def test_pool_url_resolution_precedence(tmp_path, monkeypatch):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "h")}, default_home=tmp_path)
    monkeypatch.delenv("HASHPASS_POOL", raising=False)
    assert cli._pool_url(env) is None  # noqa: SLF001
    cli.save_pool(env, "http://saved", "u")
    assert cli._pool_url(env) == "http://saved"  # noqa: SLF001
    monkeypatch.setenv("HASHPASS_POOL", "http://env")
    assert cli._pool_url(env) == "http://env"  # noqa: SLF001  (env beats the saved file)
    assert cli._pool_url(env, "http://explicit") == "http://explicit"  # noqa: SLF001  (explicit wins)


@pytest.mark.tier1
def test_resolve_pool_ref_number_and_passthrough():
    client = _FakeClient([{"number": 1, "ref": "a:1"}, {"number": 2, "ref": "b:1"}])
    assert cli._resolve_pool_ref(client, "tok", "2") == "b:1"  # noqa: SLF001
    assert cli._resolve_pool_ref(client, "tok", "x:9") == "x:9"  # noqa: SLF001  (non-numeric passthrough)
    with pytest.raises(RuntimeError, match="нет задания"):
        cli._resolve_pool_ref(client, "tok", "9")  # noqa: SLF001


def _make_task_dir(root, marker="0") -> None:
    (root / "bundle").mkdir(parents=True)
    (root / "bundle" / "c.json").write_text(f'{{"s":[{marker}]}}', encoding="utf-8")
    (root / "task-meta.json").write_text('{"image_ref":"x"}', encoding="utf-8")


def _seed_image(store, tmp_path, name) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, "1", src, ())


@pytest.mark.tier2
def test_pull_new_fetches_catalog_tasks_and_is_idempotent(registry, tmp_path):
    registry.users.add("author1", "pw", role="author")
    ac = RemoteRegistry(registry.base_url)
    atok = ac.login("author1", "pw")
    for i, name in enumerate(["lab1", "lab2"], 1):
        local = ImageStore(tmp_path / f"loc{i}")
        _seed_image(local, tmp_path, name)
        ac.push(local, f"{name}:1", token=atok)
        td = tmp_path / f"t{i}"
        td.mkdir()
        _make_task_dir(td, marker=str(i))
        ac.push_task(td, name, "1", number=i, title=f"T{i}", token=atok)

    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "stud")}, default_home=tmp_path)
    sc = RemoteRegistry(registry.base_url, cache=CredentialCache(env.creds))
    stok = sc.register("stud", "pw", full_name="A", group="G")

    expected = 2
    layers, tasks = cli.pull_new(env, registry.base_url, stok)
    assert tasks == expected
    assert layers >= expected  # each image's layer (plus any shared closure)
    store = ImageStore(env.images)
    assert store.exists("lab1:1")
    assert store.exists("lab2:1")
    assert cli.task_dir("lab1:1", store).exists()

    assert cli.pull_new(env, registry.base_url, stok) == (0, 0)  # nothing new the second time
