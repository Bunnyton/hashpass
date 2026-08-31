import pytest

from hashpass.recipe.model import (
    CopyStep,
    ExecAction,
    Recipe,
    RunStep,
    StageSpec,
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
