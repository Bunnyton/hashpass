import inspect
from dataclasses import replace

import pytest

from hashpass.canon import FileState
from hashpass.evidence import Evidence, build_evidence
from hashpass.grade import grade_stage
from hashpass.key import global_key, local_key
from hashpass.server.verify import issue_global_key, verify_evidence
from hashpass.taskcode.derive import StageChecks

_SECRET = b"real-server-secret"
_WRONG_SECRET = b"attacker-secret"
_TS = "2026-08-30T12:00:00Z"


def _checks() -> StageChecks:
    canonical = {"result.txt": FileState("file", "answer")}
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


@pytest.mark.tier1
def test_offline_then_online_happy_path():
    checks = _checks()
    correct = {"result.txt": FileState("file", "answer")}
    # 1. offline: accept → local key + evidence.
    g = grade_stage(checks, correct, task_id="task1", stage=0,
                    student_id="alice", nonce="n1", ts=_TS)
    assert g.accepted
    assert g.local_key.startswith("key{")
    assert g.evidence is not None
    # 2. online: server re-verifies + signs the identity-bound global key.
    key = issue_global_key(g.evidence, checks, server_secret=_SECRET)
    assert key == global_key(_SECRET, "alice", "task1")


@pytest.mark.tier1
def test_offline_wrong_candidate_gets_no_local_key():
    checks = _checks()
    g = grade_stage(checks, {"result.txt": FileState("file", "WRONG")},
                    task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)
    assert not g.accepted
    assert g.local_key is None


@pytest.mark.tier1
def test_server_refuses_forged_claim():
    checks = _checks()
    # A forged claim: evidence built directly from the WRONG candidate.
    forged = build_evidence(checks, {"result.txt": FileState("file", "WRONG")},
                            task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)
    assert issue_global_key(forged, checks, server_secret=_SECRET) is None


@pytest.mark.tier1
def test_global_key_unforgeable_without_secret():
    # Student cannot self-compute the credit without the server secret.
    assert global_key(_WRONG_SECRET, "alice", "task1") != global_key(_SECRET, "alice", "task1")
    # Structural: no client-side symbol exposes or accepts server_secret.
    for fn in (grade_stage, local_key, build_evidence, Evidence):
        assert "server_secret" not in inspect.signature(fn).parameters


@pytest.mark.tier1
def test_global_key_identity_bound_not_shareable():
    checks = _checks()
    correct = {"result.txt": FileState("file", "answer")}
    alice = build_evidence(checks, correct, task_id="task1", stage=0,
                           student_id="alice", nonce="n1", ts=_TS)
    bob = build_evidence(checks, correct, task_id="task1", stage=0,
                         student_id="bob", nonce="n2", ts=_TS)
    ka = issue_global_key(alice, checks, server_secret=_SECRET)
    kb = issue_global_key(bob, checks, server_secret=_SECRET)
    assert ka is not None
    assert kb is not None
    assert ka != kb  # alice's credit is not bob's


@pytest.mark.tier1
def test_stub_always_sign_server_would_fail_this_spine():
    # Threat-model guard: an always-sign server (ignoring verification) hands out credit
    # for a forged claim, whereas the real server refuses. This makes the WRONG->None
    # assertion load-bearing — swapping verification for a stub breaks the spine.
    checks = _checks()
    forged = build_evidence(checks, {"result.txt": FileState("file", "WRONG")},
                            task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)

    def always_sign(ev, _checks_ignored, *, server_secret) -> str:
        return global_key(server_secret, ev.student_id, ev.task_id)

    stub_key = always_sign(forged, checks, server_secret=_SECRET)
    real_key = issue_global_key(forged, checks, server_secret=_SECRET)
    assert stub_key is not None  # the insecure stub would grant credit
    assert real_key is None  # the real server refuses — the core guarantee
    assert stub_key != real_key


@pytest.mark.tier1
def test_server_ignores_all_client_echoed_comparator_fields():
    checks = _checks()  # server's strict reference
    wrong = build_evidence(checks, {"result.txt": FileState("file", "WRONG")},
                           task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)
    # attacker widens EVERY echoed comparator field; server must ignore them all
    forged = replace(wrong, threshold=0.0, mode="char", k=99)
    assert not verify_evidence(forged, checks)
    assert issue_global_key(forged, checks, server_secret=_SECRET) is None
