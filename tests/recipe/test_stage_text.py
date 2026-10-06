"""Tier1: `stage` takes no text; what the student reads is `say` (in a stage) or say/read before them."""
import pytest

from hashpass.recipe.model import SayAction
from hashpass.recipe.parse import parse_recipe


@pytest.mark.tier1
def test_say_in_a_stage_body_is_its_text():
    r = parse_recipe('image t:1\nstage\n  say "Спроси у системы, кто ты?"\n  solve whoami\n  observe output\n')
    assert r.stages[0].message == "Спроси у системы, кто ты?"
    assert r.stages[0].on_enter == ()                       # not an extra on-enter action


@pytest.mark.tier1
def test_task_text_before_the_stages_and_stages_that_only_check_the_path():
    # User (2026-10-05/07): «Задача одна, а проверка пути решения — из нескольких этапов. В начале
    # задал текст, а дальше реализуешь» + «текст — наверное read или что мы там писали».
    r = parse_recipe('image t:1\nsay "Почини файл в vim"\nread brief.md\n'
                     'stage\n  accept cmd "vim f"\nstage\n  check exec ok.sh\n  solve true\n')
    assert [s.message for s in r.stages] == ["", ""]
    assert r.intro[0] == SayAction("Почини файл в vim")


@pytest.mark.tier1
def test_a_stage_without_text_is_allowed_after_the_first():
    r = parse_recipe('image t:1\nstage\n  say "goal"\n  accept cmd "a"\nstage\n  accept cmd "b"\n')
    assert [s.message for s in r.stages] == ["goal", ""]


@pytest.mark.tier1
def test_stage_header_with_text_is_rejected():
    with pytest.raises(ValueError, match="stage"):
        parse_recipe('image t:1\nstage "goal"\n  accept cmd "a"\n')


@pytest.mark.tier1
def test_nothing_to_read_at_the_start_is_rejected():
    with pytest.raises(ValueError, match="first stage"):
        parse_recipe('image t:1\nstage\n  accept cmd "a"\n')


@pytest.mark.tier1
def test_two_says_in_one_stage_are_rejected():
    with pytest.raises(ValueError, match="say"):
        parse_recipe('image t:1\nstage\n  say "one"\n  say "two"\n  accept cmd "a"\n')


@pytest.mark.tier1
def test_trailing_comments_are_dropped_like_in_shell():
    r = parse_recipe(
        "image t:1  # the image\n"
        "run echo '#!/bin/sh' > /x   # quoted # stays\n"
        "run sed -i 's#a#b#' /f\n"
        "stage   # first step\n"
        '  say "Цель #1"   # the # inside quotes stays\n'
        "  # a whole-line comment inside the stage\n"
        "  solve echo hi # shell would drop it too\n"
        "  observe output\n"
        '  hint tries 3 say "Подсказка # не комментарий"  # а это комментарий\n'
    )
    assert r.name == "t" and r.version == "1"
    assert [s.cmd for s in r.steps] == ["echo '#!/bin/sh' > /x", "sed -i 's#a#b#' /f"]
    st = r.stages[0]
    assert st.message == "Цель #1"
    assert st.solve == ("echo hi",)
    assert st.hints[0].action.text == "Подсказка # не комментарий"
