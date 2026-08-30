"""Client-side grading: accept? → local (nonce) key + evidence for later server sign-off (§6/§7)."""
from dataclasses import dataclass

from hashpass.canon import Observation
from hashpass.evidence import Evidence, build_evidence
from hashpass.key import local_key
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.derive import StageChecks


@dataclass(frozen=True)
class Grade:
    """Outcome of client-side grading: acceptance + provisional local key + evidence."""

    accepted: bool
    local_key: str | None
    evidence: Evidence | None


def grade_stage(checks: StageChecks, candidate: Observation, *, task_id: str,  # noqa: PLR0913
                stage: int, student_id: str, nonce: str, ts: str, hooks=None) -> Grade:
    """Client-side: accept? → issue the local (nonce) key AND build evidence for server sign-off."""
    if not check_stage(checks, candidate, hooks=hooks, stage=stage):
        return Grade(accepted=False, local_key=None, evidence=None)
    return Grade(
        accepted=True,
        local_key=local_key(task_id, stage, nonce),
        evidence=build_evidence(checks, candidate, task_id=task_id, stage=stage,
                                student_id=student_id, nonce=nonce, ts=ts),
    )
