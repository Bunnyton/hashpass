# tests/test_runtime_loop.py
import dataclasses

import pytest

from hashpass.canon import FileState
from hashpass.hints import _STUCK_CMDS
from hashpass.play import FeedResult, PlaySession
from hashpass.progress import StageStatus, new_progress
from hashpass.sync import LocalSyncClient
from hashpass.taskcode.bundle import Bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks

_SECRET = b"server-secret-XYZ"
_TS = "2026-08-30T12:00:00Z"
_STUCK_MSG = "stuck on stage two"


def _stage(canonical) -> StageChecks:
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


def _bundle() -> Bundle:
    checks = DerivedChecks(task_id="demo", stages=(
        _stage({"s0.txt": FileState("file", "zero")}),
        _stage({"s1.txt": FileState("file", "one")}),
    ))
    hints = {1: [{"trigger": {"stuck": True}, "message": _STUCK_MSG}]}
    return Bundle(checks=checks, conditions={}, hints=hints)


def _session() -> PlaySession:
    return PlaySession(_bundle(), new_progress("demo", 2), student_id="alice", nonce="n1")


def _solve(session, rootfs, name, text) -> FeedResult:
    (rootfs / name).write_text(text, encoding="utf-8")
    return session.feed(command=f"echo {text} > {name}", rootfs=rootfs,
                        last_output=text, ts=_TS)


@pytest.mark.tier1
def test_offline_correct_advances_and_wrong_stays_locked(tmp_path):
    session = _session()
    # Wrong state (no s0.txt): must NOT advance, no key, stage stays OPEN.
    wrong = session.feed(command="ls", rootfs=tmp_path, last_output="", ts=_TS)
    assert wrong.advanced is False
    assert wrong.local_key is None
    assert session.progress.statuses[0] is StageStatus.OPEN
    # Correct state: advances offline + issues a local key.
    ok = _solve(session, tmp_path, "s0.txt", "zero")
    assert ok.advanced is True
    assert ok.local_key.startswith("key{")
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_stuck_sequence_fires_stuck_hint_and_keeps_stage_locked(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")   # advance to stage 1, resets stuck
    result = None
    for _ in range(_STUCK_CMDS):
        result = session.feed(command="ls", rootfs=tmp_path, last_output="", ts=_TS)
    assert result.hint == _STUCK_MSG
    assert result.advanced is False
    assert session.progress.statuses[1] is StageStatus.OPEN   # no key, still locked


@pytest.mark.tier1
def test_offline_then_online_reverify_upgrades_all(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")
    _solve(session, tmp_path, "s1.txt", "one")
    assert session.progress.statuses == [StageStatus.PASSED_LOCAL, StageStatus.PASSED_LOCAL]
    # Offline background re-verify changes nothing.
    offline = LocalSyncClient(server_secret=_SECRET, principal="alice", online_flag=False)
    assert session.reverify(offline) == []
    assert session.progress.statuses == [StageStatus.PASSED_LOCAL, StageStatus.PASSED_LOCAL]
    # Online re-verify with the authenticated principal upgrades both to global credit.
    online = LocalSyncClient(server_secret=_SECRET, principal="alice")
    assert session.reverify(online) == []
    assert session.progress.statuses == [StageStatus.PASSED_GLOBAL, StageStatus.PASSED_GLOBAL]


@pytest.mark.tier1
def test_forged_evidence_is_not_upgraded(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")
    # Forge the stored evidence: swap in a candidate the server will reject.
    session.evidences[0] = dataclasses.replace(
        session.evidences[0], candidate={"s0.txt": FileState("file", "FORGED")})
    online = LocalSyncClient(server_secret=_SECRET, principal="alice")
    assert session.reverify(online) == [0]
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL   # flagged, not upgraded


@pytest.mark.tier1
def test_wrong_principal_is_not_upgraded(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")
    impostor = LocalSyncClient(server_secret=_SECRET, principal="mallory")
    assert session.reverify(impostor) == [0]
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL
