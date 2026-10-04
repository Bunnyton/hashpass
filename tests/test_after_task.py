"""Tier1: the verdict screen after a task and the «next task / menu» choice."""
import pytest

from hashpass import cli


@pytest.mark.tier1
def test_next_entry_is_the_next_available_number():
    entries = [
        {"number": 3, "ref": "b/c:1", "available": True, "hidden": False},
        {"number": 4, "ref": "b/d:1", "available": False, "hidden": False},   # locked
        {"number": 5, "ref": "b/e:1", "available": True, "hidden": True},     # hidden
        {"number": 6, "ref": "b/f:1", "available": True, "hidden": False},
    ]
    assert cli._next_entry(entries, "b/c:1")["ref"] == "b/f:1"            # noqa: SLF001
    assert cli._next_entry(entries, "b/f:1")["ref"] == "b/c:1"            # wraps to the first open  # noqa: SLF001
    assert cli._next_entry(entries, "b/f:1", frozenset({"b/c:1"})) is None   # nothing left  # noqa: SLF001
    assert cli._next_entry(entries, "b/c:1", frozenset({"b/f:1"})) is None   # solved ones skipped  # noqa: SLF001
    assert cli._next_entry(entries, "ghost:1") is None                   # noqa: SLF001


@pytest.mark.tier1
def test_ask_after_task_enter_means_next_q_means_menu():
    nxt = {"number": 6, "ref": "b/f:1", "name": "f"}
    out: list[str] = []
    assert cli._ask_after_task(cli.Io(read=lambda _p: "", write=out.append, clock=lambda: ""), nxt) is True  # noqa: SLF001
    assert cli._ask_after_task(cli.Io(read=lambda _p: "q", write=out.append, clock=lambda: ""), nxt) is False  # noqa: SLF001
    assert cli._ask_after_task(cli.Io(read=lambda _p: None, write=out.append, clock=lambda: ""), nxt) is False  # noqa: SLF001
    assert cli._ask_after_task(cli.Io(read=lambda _p: "", write=out.append, clock=lambda: ""), None) is False  # noqa: SLF001
    assert any("последнее" in s for s in out)


class _FakePool:
    def __init__(self, url: str, **_kw: object) -> None:
        self.url = url

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
def test_pool_run_chains_to_the_next_task_until_menu(tmp_path, monkeypatch):
    runs: list[str] = []

    def fake_cmd_run(_env, ref, _io, *, student_id, on_complete, pool) -> int:  # noqa: ARG001
        runs.append(ref)
        on_complete(True, [])  # noqa: FBT003
        return 0
    monkeypatch.setattr(cli, "_require_pool_identity", lambda _env, _io: ("http://pool", "stud"))
    monkeypatch.setattr(cli, "_pool_token", lambda _env, _url: "tok")
    monkeypatch.setattr(cli, "RemoteRegistry", _FakePool)
    monkeypatch.setattr(cli, "task_dir", lambda _ref, _store: tmp_path)      # exists -> no pull_task
    monkeypatch.setattr(cli, "task_digest", lambda _p: "")
    monkeypatch.setattr(cli, "cmd_run", fake_cmd_run)
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    out: list[str] = []
    io = cli.Io(read=lambda _p: "", write=out.append, clock=lambda: "")   # Enter: next, always
    assert cli.cmd_pool_run(env, "1", io) == 0
    assert runs == ["b/a:1", "b/b:1"]                   # both solved -> nothing left -> stops
    assert any("последнее" in s for s in out)
    # User (2026-10-04): after exit go straight to «next task / menu» -- no «РЕШЕНО/НЕ РЕШЕНО»
    # (the console already showed it under the meme) and no «решено/зачтено» chatter.
    shown = "".join(out)
    assert "█" not in shown and "РЕШЕНО" not in shown
    assert "решено" not in shown and "зачтено" not in shown


@pytest.mark.tier1
def test_text_menu_asks_once_per_task(tmp_path, monkeypatch):
    # The text menu used to wrap cmd_pool_run in its own «следующее?» loop -> two prompts.
    runs: list[str] = []

    def fake_cmd_run(_env, ref, _io, *, student_id, on_complete, pool) -> int:  # noqa: ARG001
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
    prompts: list[str] = []
    out: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        return ""                                          # Enter: go on
    cli._run_from_menu(env, 1, cli.Io(read=read, write=out.append, clock=lambda: ""))  # noqa: SLF001
    assert runs == ["b/a:1", "b/b:1"]
    # ONE question after №1 (the old outer loop asked a second time); after №2 -- the last
    # available task -- no question at all, just the note.
    assert len(prompts) == 1 and "выйти в меню" in prompts[0]
    assert any("последнее" in s for s in out)


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
    def fake_cmd_run(_env, ref, _io, *, student_id, on_complete, pool) -> int:  # noqa: ARG001
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
    assert len(prompts) == 1 and "выйти в меню" in prompts[0]      # straight to the choice


class _OfflinePool(_FakePool):
    def submit(self, *_a: object, **_k: object) -> dict[str, object]:
        msg = "connection refused"
        raise RuntimeError(msg)


@pytest.mark.tier1
def test_failed_submit_is_still_reported(tmp_path, monkeypatch):
    # Silence is for success only: a credit that did not reach the pool must say so.
    def fake_cmd_run(_env, ref, _io, *, student_id, on_complete, pool) -> int:  # noqa: ARG001
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
