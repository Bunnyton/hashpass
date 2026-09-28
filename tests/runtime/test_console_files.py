"""Tier1: the console keeps its transcript out of $HOME, boots with a UTF-8 locale and a banner."""
from pathlib import Path

import pytest

_RT = Path(__file__).resolve().parents[2] / "src" / "hashpass" / "runtime"


@pytest.mark.tier1
def test_typescript_lives_under_run_hp_not_in_home():
    # `.hp-typescript` in the student's home was visible to `ls -a` -- engine internals leaking.
    for rel in ("usr/local/sbin/hp-bash", "etc/hp-bashrc"):
        text = (_RT / rel).read_text(encoding="utf-8")
        assert "/run/hp/typescript" in text, rel
        assert ".hp-typescript" not in text, rel
    console = (_RT / "usr/local/sbin/hp-console").read_text(encoding="utf-8")
    assert "/run/hp" in console and "chmod 755 /run/hp" in console      # other users read it


@pytest.mark.tier1
def test_console_login_gets_a_utf8_locale():
    # `su - <user>` reads /etc/default/locale via pam_env; without it LANG is unset -> C locale
    # -> readline refuses Cyrillic input.
    assert "LANG=C.UTF-8" in (_RT / "etc/default/locale").read_text(encoding="utf-8")
    # ...and, because pam_env did not deliver that through `su -` in the booted container, the
    # console exports it explicitly before the shell starts (readline reads it at startup).
    assert "export LANG=C.UTF-8" in (_RT / "usr/local/sbin/hp-console").read_text(encoding="utf-8")
    assert "LANG" in (_RT / "usr/local/sbin/hp-bash").read_text(encoding="utf-8")


@pytest.mark.tier1
def test_boot_banners_come_in_several_looks_with_random_phrases():
    banners = sorted((_RT / "etc/hp-banners").glob("*.txt"))
    assert len(banners) >= 4                                                   # noqa: PLR2004
    for b in banners:
        text = b.read_text(encoding="utf-8")
        assert len([ln for ln in text.splitlines() if ln.strip()]) >= 2, b.name   # noqa: PLR2004
    phrases = [ln for ln in (_RT / "etc/hp-phrases.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(phrases) >= 20 and len(set(phrases)) == len(phrases)            # noqa: PLR2004
    console = (_RT / "usr/local/sbin/hp-console").read_text(encoding="utf-8")
    assert "/etc/hp-banners/*.txt" in console and "hp-phrases.txt" in console and "shuf" in console
    assert "hp-banner" not in (_RT / "etc/hp-bashrc").read_text(encoding="utf-8")   # printed once


@pytest.mark.tier1
def test_hooks_follow_the_student_into_nested_shells():
    # su -, sudo -i and freshly created users must keep the prompt, the grading and the hints.
    rc = (_RT / "etc/hp-bashrc").read_text(encoding="utf-8")
    assert "__HP_LOADED" in rc and "/run/hp/port" in rc
    # ...but only the console's first shell greets the host (a nested one would replay the intro)
    assert "__hp_nested" in rc and "HP_GREETED" in rc
    console = (_RT / "usr/local/sbin/hp-console").read_text(encoding="utf-8")
    assert "/run/hp/port" in console
    base = Path(__file__).resolve().parents[2] / "src/hashpass/image/base.py"
    text = base.read_text(encoding="utf-8")
    assert "/etc/bash.bashrc" in text and "useradd -D -s /bin/bash" in text
