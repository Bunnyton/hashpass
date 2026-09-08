"""Tier1: version comparison + best-effort self-update gating."""
import pytest

from hashpass import version
from hashpass.version import check_and_update, is_newer


@pytest.mark.tier1
@pytest.mark.parametrize(("latest", "current", "expected"), [
    ("0.2.0", "0.1.0", True),
    ("v1.0.0", "0.9.9", True),
    ("1.10.0", "1.9.0", True),
    ("0.1.0", "0.1.0", False),
    ("0.1.0", "0.2.0", False),
    ("1.2.3", "1.2.3", False),
])
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


@pytest.mark.tier1
def test_disabled_by_env_never_fetches(tmp_path, monkeypatch):
    monkeypatch.setenv("HASHPASS_NO_UPDATE", "1")
    fetched = []
    assert check_and_update(tmp_path, "hashpass", [],
                            fetch=lambda: fetched.append(1) or "9.9.9") is False
    assert fetched == []


@pytest.mark.tier1
def test_disabled_by_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_NO_UPDATE", raising=False)
    assert check_and_update(tmp_path, "hashpass", ["--no-update"], fetch=lambda: "9.9.9") is False


@pytest.mark.tier1
def test_no_update_when_not_newer(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_NO_UPDATE", raising=False)
    assert check_and_update(tmp_path, "hashpass", [], fetch=lambda: version.__version__) is False


@pytest.mark.tier1
def test_throttled_after_recent_check(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_NO_UPDATE", raising=False)
    monkeypatch.setattr(version, "_pip_install", lambda _tag: False)  # attempt, then fail
    check_and_update(tmp_path, "hashpass", [], fetch=lambda: "9.9.9")
    fetched = []
    check_and_update(tmp_path, "hashpass", [], fetch=lambda: fetched.append(1) or "9.9.9")
    assert fetched == []  # second call is throttled by the stamp, so it never fetches


@pytest.mark.tier1
def test_applies_update_and_reexecs(tmp_path, monkeypatch):
    monkeypatch.delenv("HASHPASS_NO_UPDATE", raising=False)
    monkeypatch.setattr(version, "_pip_install", lambda _tag: True)
    execs = []
    monkeypatch.setattr(version.os, "execv", lambda exe, args: execs.append((exe, args)))
    assert check_and_update(tmp_path, "hashpass", ["run", "3"], fetch=lambda: "9.9.9") is True
    assert execs[0][1][1:] == ["-m", "hashpass", "run", "3"]
