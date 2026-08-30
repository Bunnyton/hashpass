from dataclasses import replace

import pytest

from hashpass.canon import FileState
from hashpass.evidence import Evidence, build_evidence
from hashpass.key import global_key
from hashpass.server.verify import issue_global_key, verify_evidence
from hashpass.taskcode.derive import StageChecks

_SECRET = b"server-only-secret"
_TS = "2026-08-30T12:00:00Z"
_THRESHOLD = 0.6
_WIDE_OPEN = 0.0


def _checks() -> StageChecks:
    canonical = {"out": FileState("file", "a\nb\nc")}
    return StageChecks(canonical=canonical, mode="line", threshold=_THRESHOLD, k=1)


def _evidence(candidate, checks) -> Evidence:
    return build_evidence(checks, candidate, task_id="task1", stage=0,
                          student_id="alice", nonce="n1", ts=_TS)


@pytest.mark.tier1
def test_correct_evidence_verifies_and_issues_key():
    checks = _checks()
    ev = _evidence({"out": FileState("file", "a\nb\nc")}, checks)
    assert verify_evidence(ev, checks)
    key = issue_global_key(ev, checks, server_secret=_SECRET)
    assert key == global_key(_SECRET, "alice", "task1")
    assert key.startswith("gkey{")


@pytest.mark.tier1
def test_wrong_evidence_refused():
    checks = _checks()
    ev = _evidence({"out": FileState("file", "X\nY\nZ")}, checks)
    assert not verify_evidence(ev, checks)
    assert issue_global_key(ev, checks, server_secret=_SECRET) is None


@pytest.mark.tier1
def test_comparator_threshold_honored():
    checks = _checks()  # threshold 0.6, line mode (Jaccard over lines)
    near = _evidence({"out": FileState("file", "a\nb\nc\nd")}, checks)  # Jaccard 3/4 = 0.75
    assert verify_evidence(near, checks)
    far = _evidence({"out": FileState("file", "a\nb\nX")}, checks)  # Jaccard 2/4 = 0.5
    assert not verify_evidence(far, checks)


@pytest.mark.tier1
def test_server_uses_own_checks_not_client_echoed_fields():
    strict = _checks()  # server reference: threshold 0.6
    ev = _evidence({"out": FileState("file", "X\nY\nZ")}, strict)  # WRONG candidate
    # Attacker widens the ECHOED comparator to trivially accept anything.
    forged = replace(ev, threshold=_WIDE_OPEN)
    # Server re-verifies with its OWN reference checks (0.6), ignoring evidence.* → still refused.
    assert not verify_evidence(forged, strict)
    assert issue_global_key(forged, strict, server_secret=_SECRET) is None
