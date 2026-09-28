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
    assert "/run/hp" in console and "chmod 700 /run/hp" in console


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
def test_boot_banner_is_big_and_printed_by_the_console():
    banner = (_RT / "etc/hp-banner").read_text(encoding="utf-8")
    assert "HASHPASS" in banner.upper() or "█" in banner
    assert banner.count("█") > 100                        # big block letters, not a small logo  # noqa: PLR2004
    console = (_RT / "usr/local/sbin/hp-console").read_text(encoding="utf-8")
    assert "/etc/hp-banner" in console
    assert "/etc/hp-banner" not in (_RT / "etc/hp-bashrc").read_text(encoding="utf-8")   # once
