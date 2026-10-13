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
