"""Tier1: a lab session -- commands typed on another machine (ssh) and `check live on` (spec 2026-11-02)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashpass.recipe.model import HintRule, SayAction, TriesCond
from hashpass.taskcode.bundle import Bundle, dump_bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskrun import TaskSession
from hashpass.taskstore import StageMeta, StoredTask, TaskMeta


def _session(tmp_path: Path, stage: StageMeta, *, web_rcs: list[int], pc_rcs: list[int] | None = None) -> tuple:
    bundle = tmp_path / "bundle"
    dump_bundle(Bundle(checks=DerivedChecks(task_id="t", stages=(StageChecks(canonical={}),)),
                       conditions={}, hints={}), bundle)
    stored = StoredTask(ref="t:1", image=None, bundle_dir=bundle, hp_src_dir=tmp_path / "src",
                        meta=TaskMeta(image_ref="t:1", stages=(stage,)))
    hp = tmp_path / "hp"
    hp.mkdir()
    sent: dict[str, list[str]] = {"pc": [], "web": []}
    pc = SimpleNamespace(rootfs=tmp_path / "rootfs",
                         check_live=lambda s: sent["pc"].append(s) or (pc_rcs or [1]).pop(0))
    web = SimpleNamespace(rootfs=tmp_path / "web",
                          check_live=lambda s: sent["web"].append(s) or web_rcs.pop(0))
    said: list[str] = []
    session = TaskSession(stored, pc, hp, student_id="s", nonce="n", sink=said.append,
                          sleep=lambda _s: None, nodes={"web": web})
    return session, sent, said


@pytest.mark.tier1
def test_check_live_on_runs_in_that_machine(tmp_path):
    stage = StageMeta(message="go", neutral=(), check="systemctl is-active nginx", on_enter=(),
                      on_pass=(), acceptance="live", check_node="web")
    s, sent, _ = _session(tmp_path, stage, web_rcs=[1, 0])
    assert s.observe("curl web", ts="2026-11-02T10:00:00").advanced is False
    assert s.observe("sudo systemctl start nginx", ts="2026-11-02T10:00:05", node="web").advanced is True
    assert sent == {"pc": [], "web": ["systemctl is-active nginx"] * 2}


@pytest.mark.tier1
def test_a_machine_command_never_passes_a_console_check(tmp_path):
    stage = StageMeta(message="go", neutral=(), check=None, on_enter=(), on_pass=(),
                      acceptance="command", accept_cmds=("ping",))
    s, _, _ = _session(tmp_path, stage, web_rcs=[])
    assert s.observe("ping pc", ts="2026-11-02T10:00:00", node="web").advanced is False
    assert s.tries == [1]
    assert s.observe("ping web", ts="2026-11-02T10:00:01").advanced is True


@pytest.mark.tier1
def test_hints_count_the_machine_commands_too(tmp_path):
    hint = HintRule(condition=TriesCond(2), action=SayAction("Загляни в журнал nginx"))
    stage = StageMeta(message="go", neutral=(), check="true", on_enter=(), on_pass=(),
                      acceptance="live", check_node="web", hints=(hint,))
    s, _, said = _session(tmp_path, stage, web_rcs=[1, 1])
    s.observe("ls", ts="2026-11-02T10:00:00", node="web")
    res = s.observe("cat x", ts="2026-11-02T10:00:01", node="web")
    assert res.advanced is False and res.hint
    assert "журнал nginx" in "".join(said)


@pytest.mark.tier1
def test_an_unknown_machine_fails_closed(tmp_path):
    stage = StageMeta(message="go", neutral=(), check="true", on_enter=(), on_pass=(),
                      acceptance="live", check_node="db")
    s, sent, _ = _session(tmp_path, stage, web_rcs=[])
    assert s.observe("x", ts="2026-11-02T10:00:00").advanced is False
    assert sent == {"pc": [], "web": []}
