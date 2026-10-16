"""Tier1: the verdict screen after a task and the «next task / menu» choice."""
import pytest

from hashpass import cli


class _FakePool:
    def __init__(self, url: str, **_kw: object) -> None:
        self.url = url

    def progress(self, *, token: str = "") -> dict[str, object]:  # noqa: ARG002
        return {}                              # nothing credited yet

    def catalog(self, *, token: str = "") -> list[dict[str, object]]:  # noqa: ARG002
        return [{"number": 1, "ref": "b/a:1", "name": "a", "available": True, "hidden": False,
                 "digest": ""},
                {"number": 2, "ref": "b/b:1", "name": "b", "available": True, "hidden": False,
                 "digest": ""}]

    def pull_many(self, *_a: object, **_k: object) -> list[str]:
        return []

    def pull_task(self, *_a: object, **_k: object) -> None:
        return None

    def submit(self, *_a: object, **_k: object) -> dict[str, object]:
        return {"status": "passed"}


@pytest.mark.tier1
def test_failed_run_shows_no_verdict(tmp_path, monkeypatch):
    # «нет такого образа» (cmd_run returns 1 without grading) must not print a red НЕ РЕШЕНО.
    monkeypatch.setattr(cli, "_require_pool_identity", lambda _env, _io: ("http://pool", "stud"))
    monkeypatch.setattr(cli, "_pool_token", lambda _env, _url: "tok")
    monkeypatch.setattr(cli, "RemoteRegistry", _FakePool)
    monkeypatch.setattr(cli, "task_dir", lambda _ref, _store: tmp_path)
    monkeypatch.setattr(cli, "task_digest", lambda _p: "")
    monkeypatch.setattr(cli, "cmd_run", lambda *_a, **_k: 1)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    out: list[str] = []
    io = cli.Io(read=lambda _p: pytest.fail("must not ask"), write=out.append, clock=lambda: "")
    assert cli.cmd_pool_run(env, "1", io) == 1
    assert not any("█" in s for s in out)


@pytest.mark.tier1
def test_unsolved_exit_shows_no_verdict_either(tmp_path, monkeypatch):
    def fake_cmd_run(_env, ref, _io, *, student_id, on_complete, pool, **_k: object) -> int:  # noqa: ARG001
        on_complete(False, [])  # noqa: FBT003
        return 0
    monkeypatch.setattr(cli, "_require_pool_identity", lambda _env, _io: ("http://pool", "stud"))
    monkeypatch.setattr(cli, "_pool_token", lambda _env, _url: "tok")
    monkeypatch.setattr(cli, "RemoteRegistry", _FakePool)
    monkeypatch.setattr(cli, "task_dir", lambda _ref, _store: tmp_path)
    monkeypatch.setattr(cli, "task_digest", lambda _p: "")
    monkeypatch.setattr(cli, "cmd_run", fake_cmd_run)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    out: list[str] = []
    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        return "q"
    assert cli.cmd_pool_run(env, "1", cli.Io(read=read, write=out.append, clock=lambda: "")) == 0
    shown = "".join(out)
    assert "РЕШЕНО" not in shown and "31m" not in shown
    assert prompts == []                                             # straight back to the menu


class _OfflinePool(_FakePool):
    def submit(self, *_a: object, **_k: object) -> dict[str, object]:
        msg = "connection refused"
        raise RuntimeError(msg)


@pytest.mark.tier1
def test_failed_submit_is_still_reported(tmp_path, monkeypatch):
    # Silence is for success only: a credit that did not reach the pool must say so.
    def fake_cmd_run(_env, ref, _io, *, student_id, on_complete, pool, **_k: object) -> int:  # noqa: ARG001
        on_complete(True, [])  # noqa: FBT003
        return 0
    monkeypatch.setattr(cli, "_require_pool_identity", lambda _env, _io: ("http://pool", "stud"))
    monkeypatch.setattr(cli, "_pool_token", lambda _env, _url: "tok")
    monkeypatch.setattr(cli, "RemoteRegistry", _OfflinePool)
    monkeypatch.setattr(cli, "task_dir", lambda _ref, _store: tmp_path)
    monkeypatch.setattr(cli, "task_digest", lambda _p: "")
    monkeypatch.setattr(cli, "cmd_run", fake_cmd_run)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    out: list[str] = []
    assert cli.cmd_pool_run(env, "1", cli.Io(read=lambda _p: "q", write=out.append, clock=lambda: "")) == 0
    assert any("нет связи" in s for s in out)


@pytest.mark.tier1
def test_after_exit_the_student_goes_straight_back_to_the_menu(tmp_path, monkeypatch):
    """User (2026-10-12): «после exit пускай выходит сразу в меню» -- one task, no question."""
    runs: list[str] = []

    def fake_cmd_run(_env, ref, _io, *, student_id, on_complete, pool, **_k: object) -> int:  # noqa: ARG001
        runs.append(ref)
        on_complete(True, [])  # noqa: FBT003
        return 0
    monkeypatch.setattr(cli, "_require_pool_identity", lambda _env, _io: ("http://pool", "stud"))
    monkeypatch.setattr(cli, "_pool_token", lambda _env, _url: "tok")
    monkeypatch.setattr(cli, "RemoteRegistry", _FakePool)
    monkeypatch.setattr(cli, "task_dir", lambda _ref, _store: tmp_path)
    monkeypatch.setattr(cli, "task_digest", lambda _p: "")
    monkeypatch.setattr(cli, "cmd_run", fake_cmd_run)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    out: list[str] = []
    io = cli.Io(read=lambda _p: pytest.fail("no question after exit"), write=out.append,
                clock=lambda: "")
    assert cli.cmd_pool_run(env, "b/a:1", io) == 0
    assert runs == ["b/a:1"]                                   # just this one, then the menu
    shown = "".join(out)
    assert "РЕШЕНО" not in shown and "следующее" not in shown
