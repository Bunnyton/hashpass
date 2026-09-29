"""Tier1: the console keeps its transcript out of $HOME, boots with a UTF-8 locale and a banner."""
import os
import subprocess
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
    assert "hp-banner" in console and "hp-phrases.txt" in console and "shuf" in console
    assert "hp-banner" not in (_RT / "etc/hp-bashrc").read_text(encoding="utf-8")   # printed once


@pytest.mark.tier1
def test_boot_banner_slogans_are_varied_and_free_of_the_machine():
    # User: «welcome to hashpass можно. Ещё разных: I love linux, I hate windows…» -- the tagline
    # is drawn from a slogan list, independent of the art; «to the machine» is gone for good.
    slogans = [ln for ln in (_RT / "etc/hp-slogans.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(slogans) >= 15 and len(set(slogans)) == len(slogans)            # noqa: PLR2004
    for must in ("welcome to hashpass", "I love linux", "I hate windows"):
        assert must in slogans
    for sl in slogans:                       # they go through sed: keep the replacement plain
        assert not set(sl) & set("|&\\{}"), sl
    for b in sorted((_RT / "etc/hp-banners").glob("*.txt")):
        text = b.read_text(encoding="utf-8")
        assert "{{SLOGAN" in text, b.name
        assert "machine" not in text.lower(), b.name


@pytest.mark.tier1
@pytest.mark.parametrize("seed", range(6))
def test_hp_banner_renders_a_slogan_into_the_art(seed):
    script = _RT / "usr/local/sbin/hp-banner"
    env = {**os.environ, "HP_BANNERS": str(_RT / "etc/hp-banners"), "HP_SLOGANS": str(_RT / "etc/hp-slogans.txt"),
           "HP_SEED": str(seed)}
    out = subprocess.run(["sh", str(script)], check=True, capture_output=True, text=True, env=env).stdout
    slogans = [ln for ln in (_RT / "etc/hp-slogans.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert "{{" not in out and "}}" not in out
    spaced = [" ".join(sl.upper()) for sl in slogans]
    assert any(sl in out for sl in slogans) or any(sp in out for sp in spaced), out
    assert len([ln for ln in out.splitlines() if ln.strip()]) >= 3                # noqa: PLR2004


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
