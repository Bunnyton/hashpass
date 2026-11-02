"""Tier1: the terminal Markdown renderer keeps code as typed."""
import re

import pytest

from hashpass.markdown import render_markdown

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", render_markdown(text))


@pytest.mark.tier1
def test_an_indented_code_line_keeps_its_stars():
    # The find brief showed `-iname "abc*"` as `"abc"`: a 4-space code line went through inline
    # styling and `*…*` became italics. Every brief writes its commands this way.
    out = _plain('Пример:\n\n    find . -iname "abc*" -o -name "cba*"\n\nи *курсив* тут\n')
    assert 'find . -iname "abc*" -o -name "cba*"' in out
    assert "и курсив тут" in out                       # prose is still styled


@pytest.mark.tier1
def test_an_indented_list_continuation_is_not_code():
    out = _plain("- пункт с *курсивом*\n  продолжение *ещё*\n")
    assert "*" not in out


@pytest.mark.tier1
def test_a_marked_match_in_an_example_is_painted_like_grep():
    # regex briefs (user 2026-11-03, after regular_tutor): an example's output shows what grep
    # found the way grep paints it -- `==кар==` in a code line is bold red, the rest stays dim.
    raw = render_markdown("Пример:\n\n    $ grep -o '.ар' pets.txt\n    ==кар==\n    в ==бар== и ==жар==\n")
    assert "\x1b[01;31mкар" in raw and "\x1b[01;31mжар" in raw
    assert "==" not in raw
    assert _plain("    в ==бар== и ==жар==\n") == "    в бар и жар"
    assert _plain("```\n<<<<<<< HEAD\n=======\n```\n") == "    <<<<<<< HEAD\n    ======="   # git conflict marks stay
    assert "\x1b[01;31m" not in render_markdown("a ==b== c")                            # prose: untouched
