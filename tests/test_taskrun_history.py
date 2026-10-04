"""Tier1: every console command lands in the session's /hp/history (HP_HISTORY for graders)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashpass.taskcode.bundle import Bundle, dump_bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskrun import TaskSession
from hashpass.taskstore import StageMeta, StoredTask, TaskMeta


def _session(tmp_path: Path) -> TaskSession:
    bundle = tmp_path / "bundle"
    dump_bundle(Bundle(checks=DerivedChecks(task_id="t", stages=(StageChecks(canonical={}),)),
                       conditions={}, hints={}), bundle)
    stage = StageMeta(message="go", neutral=(), check=None, on_enter=(), on_pass=(),
                      acceptance="command", accept_cmds=("finish",))
    stored = StoredTask(ref="t:1", image=None, bundle_dir=bundle, hp_src_dir=tmp_path / "src",
                        meta=TaskMeta(image_ref="t:1", stages=(stage,)))
    hp = tmp_path / "hp"
    hp.mkdir()
    (hp / "history").write_text("", encoding="utf-8")
    runner = SimpleNamespace(rootfs=tmp_path / "rootfs")
    return TaskSession(stored, runner, hp, student_id="s", nonce="n",
                       sink=lambda _s: None, sleep=lambda _s: None)


@pytest.mark.tier1
def test_observed_commands_are_appended_to_hp_history(tmp_path):
    # The DSL promises HP_HISTORY to `check exec`/`react` scripts; the file was created empty and
    # never filled, so a grader could not tell HOW a result was reached (chmod 111 vs chmod +x).
    s = _session(tmp_path)
    s.observe("chmod 111 test1", ts="2026-10-05T10:00:00")
    s.observe("cd target && chmod +x test1", ts="2026-10-05T10:00:05")
    s.observe("finish", ts="2026-10-05T10:00:09")
    s.observe("after the end", ts="2026-10-05T10:00:10")         # still recorded
    assert (tmp_path / "hp" / "history").read_text(encoding="utf-8").splitlines() == [
        "chmod 111 test1", "cd target && chmod +x test1", "finish", "after the end"]


@pytest.mark.tier1
def test_multiline_command_stays_one_history_line(tmp_path):
    s = _session(tmp_path)
    s.observe("for f in a b\ndo chmod +x $f\ndone", ts="2026-10-05T10:00:00")
    assert (tmp_path / "hp" / "history").read_text(encoding="utf-8").splitlines() == [
        "for f in a b; do chmod +x $f; done"]
