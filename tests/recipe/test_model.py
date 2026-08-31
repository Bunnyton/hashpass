import pytest

from hashpass.recipe.model import (
    CmdCond,
    CopyStep,
    ExecAction,
    HintRule,
    Recipe,
    RunStep,
    SayAction,
    Settings,
    ShowFileAction,
    StageSpec,
    TriesCond,
    Voice,
    image_ref,
    is_task,
)


@pytest.mark.tier1
def test_plain_image_is_not_a_task():
    r = Recipe("img", "1", (), (RunStep("echo hi"),))
    assert r.stages == ()
    assert r.hidden is None
    assert r.readme is None
    assert is_task(r) is False
    assert image_ref(r) == "img:1"


@pytest.mark.tier1
def test_stage_spec_defaults_and_task_recipe():
    stage = StageSpec(message="do it", solve=("grep x f > o",), observe=("o",))
    assert stage.exclude == ()
    assert stage.neutral == ()
    assert stage.check is None
    assert stage.on_enter == ()
    assert stage.on_pass == ()
    r = Recipe("t", "1", ("base",), (CopyStep("a/", "/b/"),), (stage,), hidden="grade/", readme="r.txt")
    assert is_task(r) is True
    assert r.stages[0].message == "do it"
    assert r.hidden == "grade/"


@pytest.mark.tier1
def test_exec_action_is_frozen_and_equatable():
    assert ExecAction("verify.sh") == ExecAction("verify.sh")
    with pytest.raises(AttributeError):
        ExecAction("x").value = "y"  # frozen


@pytest.mark.tier1
def test_recipe_interactivity_defaults():
    r = Recipe("img", "1", (), (RunStep("echo hi"),))
    assert r.voice == Voice()
    assert r.settings == Settings()
    assert r.react == ()
    assert is_task(r) is False


@pytest.mark.tier1
def test_actions_and_conditions_frozen_equatable():
    assert SayAction("hi") == SayAction("hi", dramatic=False)
    assert SayAction("hi", dramatic=True) != SayAction("hi")
    assert ShowFileAction("a.txt") == ShowFileAction("a.txt")
    assert CmdCond("grep", ("-i",), ()) == CmdCond("grep", ("-i",), ())
    with pytest.raises(AttributeError):
        SayAction("x").text = "y"


@pytest.mark.tier1
def test_stage_spec_hints_default_and_actions_widened():
    s = StageSpec(message="m", solve=("x",), on_pass=(SayAction("yo"),),
                  hints=(HintRule(TriesCond(3), ExecAction("h.sh")),))
    assert s.hints[0].condition == TriesCond(3)
    assert s.on_pass == (SayAction("yo"),)
    assert StageSpec(message="m", solve=("x",)).hints == ()


@pytest.mark.tier1
def test_settings_defaults():
    assert Settings().type_mode == "normal"
    assert Settings().type_speed == 45  # noqa: PLR2004
    assert Settings().pager is False
