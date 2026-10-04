"""Tier1: `stage silent` -- a stage that shows nothing but must be passed (tracks the right path)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashpass import cli
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import _build_meta
from hashpass.taskcode.bundle import Bundle, dump_bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskrun import FeedResult, TaskSession
from hashpass.taskstore import StoredTask, meta_from_dict, meta_to_dict

_RECIPE = """image t:1
stage silent "path: opened in vim"
  accept cmd "vim notes.txt"
stage "Fix the notes"
  accept cmd "finish"
  neutral ls
  hint tries 2 say "look at the notes"
"""


@pytest.mark.tier1
def test_parse_marks_a_silent_stage_and_keeps_its_note():
    r = parse_recipe(_RECIPE)
    assert [s.silent for s in r.stages] == [True, False]
    assert r.stages[0].message == "path: opened in vim"


@pytest.mark.tier1
@pytest.mark.parametrize("body", ['  on pass say "x"', '  on enter say "x"', '  hint tries 2 say "x"'])
def test_silent_stage_may_not_talk(body):
    with pytest.raises(ValueError, match="silent"):
        parse_recipe(f'image t:1\nstage silent "n"\n  accept cmd "a"\n{body}\nstage "g"\n  accept cmd "b"\n')


@pytest.mark.tier1
def test_last_stage_may_not_be_silent():
    with pytest.raises(ValueError, match="silent"):
        parse_recipe('image t:1\nstage "g"\n  accept cmd "a"\nstage silent "n"\n  accept cmd "b"\n')


@pytest.mark.tier1
def test_silent_flag_survives_meta_round_trip():
    meta = _build_meta("t:1", parse_recipe(_RECIPE), ["command", "command"])
    assert [s.silent for s in meta_from_dict(meta_to_dict(meta)).stages] == [True, False]
    old = meta_to_dict(meta)
    for st in old["stages"]:
        st.pop("silent")                                   # meta written by an older engine
    assert [s.silent for s in meta_from_dict(old).stages] == [False, False]


def _session(tmp_path: Path) -> TaskSession:
    recipe = parse_recipe(_RECIPE)
    meta = _build_meta("t:1", recipe, ["command", "command"])
    bundle = tmp_path / "bundle"
    dump_bundle(Bundle(checks=DerivedChecks(task_id="t", stages=(StageChecks(canonical={}),) * 2),
                       conditions={}, hints={}), bundle)
    hp = tmp_path / "hp"
    hp.mkdir()
    out: list[str] = []
    s = TaskSession(StoredTask(ref="t:1", image=None, bundle_dir=bundle, hp_src_dir=hp, meta=meta),
                    SimpleNamespace(rootfs=tmp_path), hp, student_id="s", nonce="n",
                    sink=out.append, sleep=lambda _s: None)
    s.out = out
    return s


@pytest.mark.tier1
def test_console_announces_the_visible_goal_once_and_silent_pass_prints_nothing(tmp_path):
    s = _session(tmp_path)
    shown: list[str] = []
    io = cli.Io(read=lambda _p: None, write=shown.append, clock=lambda: "t")
    cli._announce_stage(s, io)                                      # noqa: SLF001
    assert "".join(shown).count("Fix the notes") == 1 and "vim" not in "".join(shown)
    shown.clear()
    cli._render_observe(s, "vim notes.txt", "", None, 0, io)        # noqa: SLF001 -- silent passes
    assert shown == [] and s.out == []                              # nothing on screen
    cli._render_observe(s, "finish", "", None, 0, io)               # noqa: SLF001
    assert "РЕШЕНО" in "".join(shown)


@pytest.mark.tier1
def test_hints_and_tries_follow_the_shown_goal_while_silent_is_current(tmp_path):
    s = _session(tmp_path)
    s.observe("ls", ts="2026-10-05T10:00:00")                      # neutral of the SHOWN stage
    s.observe("cat notes.txt", ts="2026-10-05T10:00:01")
    res = s.observe("nano notes.txt", ts="2026-10-05T10:00:02")
    assert res.hint is not None and "look at the notes" in "".join(s.out)


@pytest.mark.tier1
def test_the_command_that_passes_a_silent_stage_is_graded_for_the_visible_one_at_once(monkeypatch):
    # `chmod +x test1` both takes the right path (silent) and reaches the goal (visible): the
    # student must not need a second command to see the next goal.
    state = {"stage": 0}
    stages = [SimpleNamespace(message="path", silent=True), SimpleNamespace(message="goal A", silent=False),
              SimpleNamespace(message="goal B", silent=False)]

    def observe(command, *, ts, output, rc=None) -> FeedResult:  # noqa: ARG001
        state["stage"] = 1
        return FeedResult(advanced=True, stage=0, local_key="")

    def check_current(*, ts) -> FeedResult:  # noqa: ARG001
        if state["stage"] == 1:
            state["stage"] = 2
            return FeedResult(advanced=True, stage=1, local_key="")
        return FeedResult(advanced=False, stage=state["stage"], local_key="")

    session = SimpleNamespace(progress=object(), meta=SimpleNamespace(stages=stages),
                              observe=observe, check_current=check_current,
                              enter=lambda: None, enter_stage=lambda: None,
                              fire_outro=lambda: None, _announced=1)
    monkeypatch.setattr(cli, "current_stage", lambda _p: state["stage"])
    shown: list[str] = []
    cli._render_observe(session, "chmod +x test1", "", None, 0,  # noqa: SLF001
                        cli.Io(read=lambda _p: None, write=shown.append, clock=lambda: "t"))
    assert state["stage"] == len(stages) - 1 and "goal B" in "".join(shown)
