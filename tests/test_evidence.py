import pytest

from hashpass.canon import FileState
from hashpass.evidence import build_evidence, evidence_from_json, evidence_to_json
from hashpass.taskcode.derive import StageChecks

_TS = "2026-08-30T12:00:00Z"
_THRESHOLD = 0.75
_K = 2
_STAGE = 3


def _checks() -> StageChecks:
    canonical = {"result.txt": FileState("file", "answer")}
    return StageChecks(canonical=canonical, mode="line", threshold=_THRESHOLD, k=_K)


@pytest.mark.tier1
def test_build_evidence_copies_comparator_and_candidate():
    checks = _checks()
    candidate = {"result.txt": FileState("file", "answer")}
    ev = build_evidence(checks, candidate, task_id="task1", stage=_STAGE,
                        student_id="alice", nonce="n1", ts=_TS)
    assert ev.candidate == candidate
    assert ev.mode == "line"
    assert ev.threshold == _THRESHOLD  # copied from checks, not defaulted
    assert ev.k == _K
    assert ev.kind == "fuzzy"
    assert ev.stage == _STAGE
    assert ev.ts == _TS


@pytest.mark.tier1
def test_evidence_json_round_trip_with_null_filestate():
    checks = _checks()
    candidate = {"result.txt": FileState("file", "answer"),
                 "d": FileState("dir", None)}
    ev = build_evidence(checks, candidate, task_id="task1", stage=0,
                        student_id="alice", nonce="n1", ts=_TS)
    again = evidence_from_json(evidence_to_json(ev))
    assert again == ev
    assert again.candidate["d"] == FileState("dir", None)  # FileState(None) via JSON null
