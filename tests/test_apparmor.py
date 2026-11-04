"""Tier1: task consoles run in an AppArmor namespace of their own -- the host's profiles stay out."""
from pathlib import Path

import pytest

from hashpass import apparmor

ISOLATED = ["aa-exec", "-n", "hashpass", "-p", "unconfined", "--"]


def _host(tmp_path: Path, *, enabled: str = "Y", namespaces: bool = True) -> dict:
    (tmp_path / "enabled").write_text(enabled + "\n", encoding="utf-8")
    if namespaces:
        (tmp_path / "namespaces").mkdir(exist_ok=True)
    return {"enabled": tmp_path / "enabled", "namespaces": tmp_path / "namespaces"}


class _Sudo:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok, self.calls = ok, []

    def __call__(self, argv: list[str]) -> bool:
        self.calls.append(argv)
        return self.ok


@pytest.mark.tier1
def test_under_emulation_the_console_leaves_the_hosts_profiles(tmp_path, monkeypatch) -> None:
    """Ubuntu arm64, 2026-11-04: the host's /usr/bin/man profile attached to the console's man."""
    monkeypatch.delenv("HASHPASS_AA_ISOLATE", raising=False)
    monkeypatch.setattr(apparmor, "DEFAULT_ON", True)
    run = _Sudo()
    got = apparmor.prefix(emulated=True, run=run, which=lambda _c: "/usr/bin/aa-exec", **_host(tmp_path))
    assert got == ISOLATED
    assert ["sudo", "-n", "mkdir", "-p", str(tmp_path / "namespaces" / "hashpass")] in run.calls
    assert run.calls[-1] == ["sudo", "-n", *ISOLATED, "true"]          # proven before a console relies on it


@pytest.mark.tier1
def test_a_failed_probe_keeps_the_old_way(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HASHPASS_AA_ISOLATE", "1")
    got = apparmor.prefix(emulated=True, run=_Sudo(ok=False), which=lambda _c: "/usr/bin/aa-exec", **_host(tmp_path))
    assert got == []


@pytest.mark.tier1
@pytest.mark.parametrize(("host", "which"), [
    ({"enabled": "N"}, "/usr/bin/aa-exec"),            # AppArmor off: nothing to leave
    ({"namespaces": False}, "/usr/bin/aa-exec"),       # a kernel without policy namespaces
    ({}, None),                                        # no aa-exec
])
def test_no_apparmor_means_nothing_to_do(tmp_path, monkeypatch, host: dict, which: str | None) -> None:
    monkeypatch.setenv("HASHPASS_AA_ISOLATE", "1")
    run = _Sudo()
    assert apparmor.prefix(emulated=True, run=run, which=lambda _c: which, **_host(tmp_path, **host)) == []
    assert run.calls == []


@pytest.mark.tier1
def test_native_x86_stays_as_it_was_unless_asked(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HASHPASS_AA_ISOLATE", raising=False)
    run = _Sudo()
    assert apparmor.prefix(emulated=False, run=run, which=lambda _c: "/usr/bin/aa-exec", **_host(tmp_path)) == []
    assert run.calls == []
    monkeypatch.setenv("HASHPASS_AA_ISOLATE", "1")
    assert apparmor.prefix(emulated=False, run=run, which=lambda _c: "/usr/bin/aa-exec", **_host(tmp_path)) == ISOLATED
    monkeypatch.setenv("HASHPASS_AA_ISOLATE", "0")
    assert apparmor.prefix(emulated=True, run=_Sudo(), which=lambda _c: "/usr/bin/aa-exec", **_host(tmp_path)) == []


@pytest.mark.tier1
def test_the_console_and_lab_machines_start_through_the_prefix(monkeypatch) -> None:
    monkeypatch.setattr(apparmor, "prefix", lambda **_k: ISOLATED)
    assert apparmor.nspawn_cmd() == ["sudo", *ISOLATED, "systemd-nspawn"]
    for src in ("cli.py", "runner/nspawn.py"):
        text = (Path(apparmor.__file__).parent / src).read_text(encoding="utf-8")
        assert "apparmor.nspawn_cmd()" in text, src


@pytest.mark.tier1
def test_off_by_default_until_proven_live(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HASHPASS_AA_ISOLATE", raising=False)
    run = _Sudo()
    assert apparmor.prefix(emulated=True, run=run, which=lambda _c: "/usr/bin/aa-exec", **_host(tmp_path)) == []
    assert run.calls == []
