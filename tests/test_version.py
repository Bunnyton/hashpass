"""Tier1: self-update on launch -- follow the commit on `main`, best-effort, at most once."""
import subprocess

import pytest

from hashpass import version
from hashpass.version import check_and_update

OLD, NEW = "a" * 40, "b" * 40
TWO_TRIES = 2


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


@pytest.mark.tier1
def test_installed_commit_reads_archive_url(monkeypatch):
    """The installer pulls one commit's tarball (fast), not a full git clone -- sha is in the URL."""
    class _Dist:
        def read_text(self, _name: str) -> str:
            return (f'{{"url": "https://github.com/Bunnyton/hashpass/archive/{OLD}.tar.gz", '
                    '"archive_info": {}}')

    monkeypatch.setattr(version.metadata, "distribution", lambda _n: _Dist())
    assert version.installed_commit() == OLD


class _Run:
    """Fake subprocess.run: fail the first `fail` pip installs with an SSL error, record the rest."""

    def __init__(self, fail: int) -> None:
        self.fail, self.calls = fail, []

    def __call__(self, cmd: list[str], **kw: object) -> subprocess.CompletedProcess:
        if "--help" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        self.calls.append((cmd, kw.get("env")))
        if len(self.calls) <= self.fail:
            raise subprocess.CalledProcessError(1, cmd, stderr="CERTIFICATE_VERIFY_FAILED self-signed")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


@pytest.mark.tier1
def test_pip_install_uses_commit_tarball(monkeypatch):
    run = _Run(fail=0)
    monkeypatch.setattr(version.subprocess, "run", run)
    assert version._pip_install(NEW)  # noqa: SLF001 is True
    assert run.calls[0][0][-1] == f"https://github.com/Bunnyton/hashpass/archive/{NEW}.tar.gz"


@pytest.mark.tier1
def test_pip_install_retries_trusting_hosts_on_self_signed(monkeypatch):
    """A school MITM proxy with a self-signed cert: the second try trusts github/pypi."""
    run = _Run(fail=1)
    monkeypatch.setattr(version.subprocess, "run", run)
    assert version._pip_install(NEW)  # noqa: SLF001 is True
    assert len(run.calls) == TWO_TRIES
    trusted = (run.calls[1][1] or {}).get("PIP_TRUSTED_HOST", "")
    for host in ("github.com", "codeload.github.com", "pypi.org", "files.pythonhosted.org"):
        assert host in trusted.split()


@pytest.mark.tier1
def test_remote_commit_retries_without_ssl_verify(monkeypatch):
    calls = []

    def run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess:
        calls.append(cmd)
        if "http.sslVerify=false" not in cmd:
            raise subprocess.CalledProcessError(128, cmd, stderr="SSL certificate problem: self-signed")
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{NEW}\trefs/heads/main\n", stderr="")

    monkeypatch.setattr(version.subprocess, "run", run)
    assert version.remote_commit() == NEW
    assert len(calls) == TWO_TRIES


@pytest.mark.tier1
def test_a_running_pool_updates_itself_and_restarts_when_idle():
    # User (2026-10-12): «пускай hashengine тоже автоматом обновляется до последней версии». The
    # pool (`hashengine serve`) runs for weeks: it checks `main` every few minutes, installs a new
    # commit, waits until no request is in flight and restarts itself -- never with --reset-admin.
    from hashpass.version import watch_for_updates  # noqa: PLC0415
    events: list[object] = []
    busy = [True, True, False]
    commits = iter([OLD, NEW])
    watch_for_updates(
        "hashengine", ["serve", "--port", "8080", "--reset-admin"],
        rounds=2, sleep=lambda s: events.append(("sleep", s)),
        installed=lambda: OLD, fetch=lambda: next(commits),
        install=lambda c: events.append(("install", c)) or True,
        idle=lambda: not busy.pop(0), restart=lambda argv: events.append(("restart", argv)),
        write=lambda _s: None)
    assert ("install", NEW) in events
    assert events[-1] == ("restart", ["serve", "--port", "8080"])
    rounds_and_idle_waits = 4                                    # 2 rounds + waited for idle twice
    assert sum(1 for e in events if e[0] == "sleep") >= rounds_and_idle_waits


@pytest.mark.tier1
def test_the_pool_watch_leaves_a_developer_checkout_alone():
    from hashpass.version import watch_for_updates  # noqa: PLC0415
    events: list[object] = []
    watch_for_updates("hashengine", ["serve"], rounds=3, sleep=lambda _s: None,
                      installed=lambda: None, fetch=lambda: events.append("fetch") or NEW,
                      install=lambda _c: events.append("install") or True,
                      idle=lambda: True, restart=lambda _a: events.append("restart"),
                      write=lambda _s: None)
    assert events == []
