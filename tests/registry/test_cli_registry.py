import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore


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
