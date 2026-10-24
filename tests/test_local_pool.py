"""
Tier1: an offline install keeps its pool on the student's own machine.

User 2026-10-24: «сделай оффлайн установщик, полный, абсолютно автономный». The bundle carries a
copy of the pool (tasks, courses, the catalog); `pool.json` says `"local": true`, and every launch
of hashpass starts that pool when it is not running -- the student never starts a server by hand.
"""
import json

import pytest

from hashpass import cli


def _env(tmp_path, pool: dict) -> cli.Home:
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    (env.root / "pool.json").write_text(json.dumps(pool), encoding="utf-8")
    return env


class _Spawned:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv: list[str], **kw: object) -> object:
        self.calls.append((list(argv), kw))
        return object()


@pytest.mark.tier1
def test_a_local_pool_that_is_down_is_started_on_its_own_port(tmp_path, monkeypatch) -> None:
    env = _env(tmp_path, {"url": "http://127.0.0.1:47080", "user": "", "local": True})
    spawned = _Spawned()
    up = iter([False, True])
    monkeypatch.setattr(cli, "_registry_reachable", lambda _url: next(up))
    monkeypatch.setattr(cli.subprocess, "Popen", spawned)
    cli.ensure_local_pool(env)
    [(argv, kw)] = spawned.calls
    assert argv[1:] == ["-m", "hashpass", "--no-update", "serve", "--host", "127.0.0.1", "--port", "47080"]
    assert kw["env"]["HASHPASS_HOME"] == str(env.root)
    assert kw["start_new_session"] is True                    # outlives this launch


@pytest.mark.tier1
def test_a_running_local_pool_and_a_remote_pool_are_left_alone(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *_a, **_k: pytest.fail("must not start a pool"))
    monkeypatch.setattr(cli, "_registry_reachable", lambda _url: True)
    cli.ensure_local_pool(_env(tmp_path / "a", {"url": "http://127.0.0.1:47080", "local": True}))
    monkeypatch.setattr(cli, "_registry_reachable", lambda _url: False)
    cli.ensure_local_pool(_env(tmp_path / "b", {"url": "https://135.106.177.228:8080", "user": "x"}))


@pytest.mark.tier1
def test_signing_in_keeps_the_local_mark(tmp_path) -> None:
    """The TUI's login rewrites pool.json; the next launch must still start the local pool."""
    env = _env(tmp_path, {"url": "http://127.0.0.1:47080", "user": "", "local": True})
    cli.save_pool(env, "http://127.0.0.1:47080", "student1")
    assert cli.load_pool(env) == {"url": "http://127.0.0.1:47080", "user": "student1", "local": True}
    cli.save_pool(env, "https://pool.example:8080", "student1")     # moved to a real pool
    assert "local" not in cli.load_pool(env)
