"""Server-side re-verification of evidence + HMAC signing of the global key (§6)."""
from hashpass.canon import matches
from hashpass.evidence import Evidence
from hashpass.key import global_key
from hashpass.taskcode.derive import StageChecks


def verify_evidence(evidence: Evidence, checks: StageChecks) -> bool:
    """
    Re-verify: recompute acceptance from the submitted candidate against the reference canonical.

    Precondition: `checks` MUST be the reference checks for THIS evidence's (task_id, stage);
    the caller selects them by that key. `checks` carries no identity, so a wrong pairing would
    verify against the wrong reference.
    """
    return matches(checks.canonical, evidence.candidate,
                   threshold=checks.threshold, mode=checks.mode, k=checks.k)


def issue_global_key(evidence: Evidence, checks: StageChecks, *,
                     server_secret: bytes) -> str | None:
    """
    Verify evidence, then HMAC-sign the identity-bound global key; None if verification fails.

    The signed credit binds to the CLIENT-SUPPLIED `evidence.student_id`; authenticating that
    the requester owns that identity is transport-layer (Plan F) responsibility — Plan F MUST
    bind the authenticated principal to `evidence.student_id` and reject mismatches. Enforcing
    (task_id, stage) pairing belongs there too.
    """
    if not verify_evidence(evidence, checks):
        return None
    return global_key(server_secret, evidence.student_id, evidence.task_id)
