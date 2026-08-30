import inspect

import pytest

from hashpass.canon import FileState
from hashpass.evidence import Evidence, build_evidence
from hashpass.progress import StageStatus, TaskProgress, mark_passed_local, new_progress
from hashpass.sync import LocalSyncClient, background_reverify
from hashpass.taskcode.derive import DerivedChecks, StageChecks

_SECRET = b"server-secret-XYZ"
_TS = "2026-08-30T12:00:00Z"
_ANSWER = {"result.txt": FileState("file", "answer")}


def _checks(task_id: str = "demo") -> DerivedChecks:
    stage = StageChecks(canonical=_ANSWER, mode="line", threshold=1.0, k=1)
    return DerivedChecks(task_id=task_id, stages=(stage,))


def _passed_local(task_id: str = "demo") -> TaskProgress:
    progress = new_progress(task_id, 1)
    mark_passed_local(progress, 0)
    return progress


def _evidence(checks: DerivedChecks, candidate, *, student_id="alice", task_id="demo") -> Evidence:
    return build_evidence(checks.stages[0], candidate, task_id=task_id, stage=0,
                          student_id=student_id, nonce="n1", ts=_TS)


@pytest.mark.tier1
def test_online_reverify_upgrades_correct_stage_to_global():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, _ANSWER)
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == []
    assert progress.statuses[0] is StageStatus.PASSED_GLOBAL


@pytest.mark.tier1
def test_forged_candidate_is_rejected_and_flagged():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, {"result.txt": FileState("file", "WRONG")})
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == [0]
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL  # flagged, not upgraded


@pytest.mark.tier1
def test_wrong_principal_is_rejected():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, _ANSWER, student_id="alice")
    sync = LocalSyncClient(server_secret=_SECRET, principal="mallory")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == [0]
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_task_id_mismatch_is_skipped_and_never_signed():
    checks = _checks(task_id="demo")
    progress = _passed_local(task_id="demo")
    # Candidate + principal are correct; ONLY the task_id is wrong -> must be skipped, never signed.
    ev = _evidence(checks, _ANSWER, task_id="other-task")
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == [0]
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_offline_reverify_changes_nothing():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, _ANSWER)
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice", online_flag=False)
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == []
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_local_sync_client_holds_secret_but_signature_is_narrow():
    # LocalSyncClient models the SERVER; a real client only sees the SyncClient protocol,
    # whose submit/online never expose server_secret.
    params = inspect.signature(background_reverify).parameters
    assert "server_secret" not in params
