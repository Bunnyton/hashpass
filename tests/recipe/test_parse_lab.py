"""Labs (spec 2026-11-02): `check live on <machine>` and `settings hosts`."""
import pytest

from hashpass.recipe.parse import parse_recipe
from hashpass.taskstore import StageMeta, meta_from_dict, meta_to_dict, TaskMeta

_HEAD = 'image t:1\nsay "Go"\n'


@pytest.mark.tier1
def test_check_live_on_names_the_machine() -> None:
    r = parse_recipe(_HEAD + "stage\n  solve true\n  check live on web test -f /x\n")
    assert r.stages[0].check_live == "test -f /x"
    assert r.stages[0].check_node == "web"


@pytest.mark.tier1
def test_plain_check_live_is_the_console() -> None:
    r = parse_recipe(_HEAD + "stage\n  solve true\n  check live test -f /x\n")
    assert r.stages[0].check_live == "test -f /x"
    assert r.stages[0].check_node is None


@pytest.mark.tier1
def test_check_live_on_needs_a_machine_and_a_command() -> None:
    with pytest.raises(ValueError, match="check live on"):
        parse_recipe(_HEAD + "stage\n  solve true\n  check live on web\n")


@pytest.mark.tier1
def test_settings_hosts() -> None:
    assert parse_recipe(_HEAD + "settings\n  hosts off\nstage\n  solve true\n").settings.hosts is False
    assert parse_recipe(_HEAD + "stage\n  solve true\n").settings.hosts is True


@pytest.mark.tier1
def test_stage_meta_keeps_the_machine() -> None:
    sm = StageMeta(message="m", neutral=(), check="true", on_enter=(), on_pass=(),
                   acceptance="live", check_node="web")
    back = meta_from_dict(meta_to_dict(TaskMeta(image_ref="t:1", stages=(sm,))))
    assert back.stages[0].check_node == "web"
    old = meta_to_dict(TaskMeta(image_ref="t:1", stages=(sm,)))
    del old["stages"][0]["check_node"]
    assert meta_from_dict(old).stages[0].check_node is None
