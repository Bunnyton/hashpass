"""Tier1: `stage` takes no text; the goal is a bare quoted line in its body; `#` comments anywhere."""
import pytest

from hashpass.recipe.parse import parse_recipe


@pytest.mark.tier1
def test_goal_is_a_bare_quoted_line_inside_the_stage():
    r = parse_recipe('image t:1\nstage\n  "Спроси у системы, кто ты?"\n  solve whoami\n  observe output\n')
    assert r.stages[0].message == "Спроси у системы, кто ты?"


@pytest.mark.tier1
def test_a_stage_without_text_is_allowed_after_the_first():
    r = parse_recipe('image t:1\nstage\n  "goal"\n  accept cmd "a"\nstage\n  accept cmd "b"\n')
    assert [s.message for s in r.stages] == ["goal", ""]


@pytest.mark.tier1
def test_stage_header_with_text_is_rejected():
    with pytest.raises(ValueError, match="stage"):
        parse_recipe('image t:1\nstage "goal"\n  accept cmd "a"\n')


@pytest.mark.tier1
def test_first_stage_needs_text():
    with pytest.raises(ValueError, match="first stage"):
        parse_recipe('image t:1\nstage\n  accept cmd "a"\n')


@pytest.mark.tier1
def test_two_text_lines_in_one_stage_are_rejected():
    with pytest.raises(ValueError, match="text"):
        parse_recipe('image t:1\nstage\n  "one"\n  "two"\n  accept cmd "a"\n')


@pytest.mark.tier1
def test_trailing_comments_are_dropped_like_in_shell():
    r = parse_recipe(
        "image t:1  # the image\n"
        "run echo '#!/bin/sh' > /x   # quoted # stays\n"
        "run sed -i 's#a#b#' /f\n"
        "stage   # first step\n"
        '  "Цель #1"   # the goal; the # inside quotes stays\n'
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


@pytest.mark.tier1
def test_task_text_at_the_start_and_stages_that_only_check_the_path():
    # User (2026-10-05): «Задача одна, а проверка пути решения — из нескольких этапов. В начале
    # задал текст, а дальше реализуешь. Если один этап, то можно в нем писать.»
    r = parse_recipe('image t:1\nsay "hi"\n"Почини файл в vim"\n'
                     'stage\n  accept cmd "vim f"\nstage\n  check exec ok.sh\n  solve true\n')
    assert [s.message for s in r.stages] == ["Почини файл в vim", ""]
    assert r.intro[0].text == "hi"


@pytest.mark.tier1
def test_task_text_and_first_stage_text_together_are_ambiguous():
    with pytest.raises(ValueError, match="text"):
        parse_recipe('image t:1\n"task"\nstage\n  "stage text"\n  accept cmd "a"\n')


@pytest.mark.tier1
def test_task_text_after_the_stages_is_rejected():
    with pytest.raises(ValueError, match="text"):
        parse_recipe('image t:1\nstage\n  "g"\n  accept cmd "a"\n"late"\n')
