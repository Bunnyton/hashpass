"""Per-stage Evidence record: the student's captured signature + pinned comparator params (§6)."""
import json
from dataclasses import dataclass

from hashpass.canon import FileState, Observation
from hashpass.taskcode.derive import StageChecks


@dataclass(frozen=True)
class Evidence:
    """Per-stage acceptance evidence the server re-verifies before signing the global key (§6)."""

    task_id: str
    stage: int
    student_id: str
    nonce: str
    ts: str
    kind: str
    candidate: Observation
    mode: str
    threshold: float
    k: int


def build_evidence(checks: StageChecks, candidate: Observation, *, task_id: str,  # noqa: PLR0913
                   stage: int, student_id: str, nonce: str, ts: str,
                   kind: str = "fuzzy") -> Evidence:
    """Snapshot the candidate + copy the pinned comparator params (mode/threshold/k) from checks."""
    return Evidence(
        task_id=task_id,
        stage=stage,
        student_id=student_id,
        nonce=nonce,
        ts=ts,
        kind=kind,
        candidate=candidate,
        mode=checks.mode,
        threshold=checks.threshold,
        k=checks.k,
    )


def evidence_to_json(ev: Evidence) -> str:
    """Serialize Evidence to JSON; Observation -> {path: {kind, text}}."""
    return json.dumps({
        "task_id": ev.task_id,
        "stage": ev.stage,
        "student_id": ev.student_id,
        "nonce": ev.nonce,
        "ts": ev.ts,
        "kind": ev.kind,
        "candidate": {path: {"kind": fs.kind, "text": fs.text}
                      for path, fs in ev.candidate.items()},
        "mode": ev.mode,
        "threshold": ev.threshold,
        "k": ev.k,
    })


def evidence_from_json(s: str) -> Evidence:
    """Reconstruct Evidence (incl. FileState) from JSON."""
    d = json.loads(s)
    candidate = {path: FileState(fs["kind"], fs["text"])
                 for path, fs in d["candidate"].items()}
    return Evidence(
        task_id=d["task_id"],
        stage=d["stage"],
        student_id=d["student_id"],
        nonce=d["nonce"],
        ts=d["ts"],
        kind=d["kind"],
        candidate=candidate,
        mode=d["mode"],
        threshold=d["threshold"],
        k=d["k"],
    )
