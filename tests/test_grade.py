import inspect

import pytest

from hashpass.canon import FileState
from hashpass.grade import Grade, grade_stage
from hashpass.taskcode.derive import StageChecks

_TS = "2026-08-30T12:00:00Z"


def _checks() -> StageChecks:
    canonical = {"result.txt": FileState("file", "answer")}
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


@pytest.mark.tier1
def test_grade_accept_path_issues_local_key_and_evidence():
    checks = _checks()
    candidate = {"result.txt": FileState("file", "answer")}
    g = grade_stage(checks, candidate, task_id="task1", stage=0,
                    student_id="alice", nonce="n1", ts=_TS)
    assert isinstance(g, Grade)
    assert g.accepted
    assert g.local_key is not None
    assert g.local_key.startswith("key{")
    assert g.evidence is not None
    assert g.evidence.candidate == candidate


@pytest.mark.tier1
def test_grade_reject_path_no_key_no_evidence():
    checks = _checks()
    g = grade_stage(checks, {"result.txt": FileState("file", "WRONG")},
                    task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)
    assert not g.accepted
    assert g.local_key is None
    assert g.evidence is None


@pytest.mark.tier1
def test_grade_stage_never_takes_server_secret():
    # Client never holds the secret: structural guarantee.
    assert "server_secret" not in inspect.signature(grade_stage).parameters
