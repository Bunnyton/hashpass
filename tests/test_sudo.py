"""Tier1: the student CLI gets sudo up front, in the plain terminal (not under the TUI)."""
import subprocess

import pytest

from hashpass import sudo


def _run_log(monkeypatch, codes: dict[str, int]) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(argv: list[str], **_kw: object) -> subprocess.CompletedProcess:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, codes.get(" ".join(argv[:3]), 1))

    monkeypatch.setattr(sudo.subprocess, "run", fake)
    monkeypatch.setattr(sudo.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(sudo.shutil, "which", lambda _n: "/usr/bin/sudo")
    monkeypatch.setattr(sudo, "_start_keepalive", lambda: None)
    return calls


@pytest.mark.tier1
def test_passwordless_sudo_asks_nothing(monkeypatch):
    calls = _run_log(monkeypatch, {"sudo -n systemd-nspawn": 0})
    assert sudo.ensure_sudo(lambda _s: None) is True
    assert all("-v" not in c for c in calls)


@pytest.mark.tier1
def test_password_is_asked_visibly_on_a_terminal(monkeypatch):
    calls = _run_log(monkeypatch, {"sudo -v -p": 0})
    monkeypatch.setattr(sudo.sys.stdin, "isatty", lambda: True)
    out: list[str] = []
    assert sudo.ensure_sudo(out.append) is True
    assert calls[-1][:2] == ["sudo", "-v"]
    assert "нужен sudo" in "".join(out)


@pytest.mark.tier1
def test_failed_password_warns_but_does_not_raise(monkeypatch):
    _run_log(monkeypatch, {})
    monkeypatch.setattr(sudo.sys.stdin, "isatty", lambda: True)
    out: list[str] = []
    assert sudo.ensure_sudo(out.append) is False
    assert "sudo не получен" in "".join(out)


@pytest.mark.tier1
def test_root_needs_nothing(monkeypatch):
    calls = _run_log(monkeypatch, {})
    monkeypatch.setattr(sudo.os, "geteuid", lambda: 0)
    assert sudo.ensure_sudo(lambda _s: None) is True
    assert calls == []
