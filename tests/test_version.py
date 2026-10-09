"""Tier1: self-update on launch -- follow the commit on `main`, best-effort, at most once."""
import pytest

from hashpass import version
from hashpass.version import check_and_update

OLD, NEW = "a" * 40, "b" * 40


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:
    monkeypatch.delenv("HASHPASS_NO_UPDATE", raising=False)
    monkeypatch.setenv("HASHPASS_JUST_UPDATED", "")   # recorded -> restored even if the code sets it
    monkeypatch.delenv("HASHPASS_JUST_UPDATED")


def _quiet(**kw: object) -> dict[str, object]:
    return {"installed": lambda: OLD, "write": lambda _s: None, **kw}


@pytest.mark.tier1
def test_disabled_by_env_never_fetches(monkeypatch):
    monkeypatch.setenv("HASHPASS_NO_UPDATE", "1")
    fetched = []
    assert check_and_update("hashpass", [], **_quiet(fetch=lambda: fetched.append(1) or NEW)) is False
    assert fetched == []


@pytest.mark.tier1
def test_disabled_by_flag():
    assert check_and_update("hashpass", ["--no-update"], **_quiet(fetch=lambda: NEW)) is False


@pytest.mark.tier1
def test_same_commit_does_nothing(monkeypatch):
    monkeypatch.setattr(version, "_pip_install", lambda _c: pytest.fail("must not install"))
    assert check_and_update("hashpass", [], **_quiet(fetch=lambda: OLD)) is False


@pytest.mark.tier1
def test_editable_or_offline_does_nothing(monkeypatch):
    monkeypatch.setattr(version, "_pip_install", lambda _c: pytest.fail("must not install"))
    assert check_and_update("hashpass", [], **_quiet(installed=lambda: None, fetch=lambda: NEW)) is False
    assert check_and_update("hashpass", [], **_quiet(fetch=lambda: None)) is False


@pytest.mark.tier1
def test_new_commit_installs_and_reexecs_once(monkeypatch):
    installed = []
    monkeypatch.setattr(version, "_pip_install", lambda c: installed.append(c) or True)
    execs = []
    monkeypatch.setattr(version.os, "execv", lambda exe, args: execs.append((exe, args)))
    out: list[str] = []
    assert check_and_update("hashpass", ["run", "3"],
                            **_quiet(fetch=lambda: NEW, write=out.append)) is True
    assert installed == [NEW]
    assert execs[0][1][1:] == ["-m", "hashpass", "run", "3"]
    assert "обновляю hashpass" in "".join(out)
    # the re-exec'd process must not update again (env flag survives execv)
    assert check_and_update("hashpass", [], **_quiet(fetch=lambda: NEW)) is False


@pytest.mark.tier1
def test_failed_pip_keeps_running(monkeypatch):
    monkeypatch.setattr(version, "_pip_install", lambda _c: False)
    out: list[str] = []
    assert check_and_update("hashpass", [], **_quiet(fetch=lambda: NEW, write=out.append)) is False
    assert "не удалось" in "".join(out)


@pytest.mark.tier1
def test_installed_commit_reads_pip_direct_url(monkeypatch):
    class _Dist:
        def read_text(self, _name: str) -> str:
            return ('{"url": "https://github.com/Bunnyton/hashpass", '
                    f'"vcs_info": {{"commit_id": "{OLD}", "vcs": "git"}}}}')

    monkeypatch.setattr(version.metadata, "distribution", lambda _n: _Dist())
    assert version.installed_commit() == OLD
