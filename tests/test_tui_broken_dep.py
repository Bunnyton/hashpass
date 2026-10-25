"""
Tier1: a broken textual install opens the text menu with the fix, not a traceback.

User 2026-10-25 (Ubuntu 24.04): `hashpass` died on `from textual.app import App` --
AttributeError from the system typing_extensions 4.10 under python3.13.
"""
import builtins
import sys

import pytest

from hashpass import cli


def _io(out: list[str]) -> cli.Io:
    return cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")


@pytest.mark.tier1
def test_a_broken_textual_is_reported_with_the_fix(monkeypatch) -> None:
    real = builtins.__import__

    def broken(name: str, *a: object, **k: object) -> object:
        if name == "hashpass.tui":
            msg = "attribute '__default__' of 'typing.ParamSpec' objects is not writable"
            raise AttributeError(msg)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", broken)
    out: list[str] = []
    assert cli._load_tui(_io(out)) is None  # noqa: SLF001
    text = "".join(out)
    assert "--ignore-installed" in text and sys.executable in text


@pytest.mark.tier1
def test_a_missing_textual_still_says_install_it(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "hashpass.tui", None)
    out: list[str] = []
    assert cli._load_tui(_io(out)) is None  # noqa: SLF001
    assert "textual не установлен" in "".join(out)
