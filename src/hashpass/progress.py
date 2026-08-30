"""Per-stage progress state machine + provisional/server reconciliation (§7)."""
from dataclasses import dataclass
from enum import Enum


class StageStatus(Enum):
    """Lifecycle of one stage: locked -> open -> passed_local -> passed_global."""

    LOCKED = "locked"
    OPEN = "open"
    PASSED_LOCAL = "passed_local"
    PASSED_GLOBAL = "passed_global"


@dataclass
class TaskProgress:
    """Mutable per-stage progress for one task (stage 0 OPEN, the rest LOCKED at start)."""

    task_id: str
    statuses: list[StageStatus]


def new_progress(task_id: str, n_stages: int) -> TaskProgress:
    """Fresh progress: stage 0 OPEN, the rest LOCKED."""
    statuses = [StageStatus.LOCKED] * n_stages
    if statuses:
        statuses[0] = StageStatus.OPEN
    return TaskProgress(task_id=task_id, statuses=statuses)


def current_stage(progress: TaskProgress) -> int | None:
    """First OPEN stage index; None once every stage is passed."""
    for i, status in enumerate(progress.statuses):
        if status is StageStatus.OPEN:
            return i
    return None


def mark_passed_local(progress: TaskProgress, stage: int) -> None:
    """Mark a stage locally passed and OPEN the next LOCKED stage."""
    progress.statuses[stage] = StageStatus.PASSED_LOCAL
    nxt = stage + 1
    if nxt < len(progress.statuses) and progress.statuses[nxt] is StageStatus.LOCKED:
        progress.statuses[nxt] = StageStatus.OPEN


def mark_passed_global(progress: TaskProgress, stage: int) -> None:
    """Upgrade a stage to PASSED_GLOBAL (idempotent)."""
    progress.statuses[stage] = StageStatus.PASSED_GLOBAL


def reconcile(progress: TaskProgress, server_passed: set[int]) -> list[int]:
    """
    Upgrade server-confirmed stages to GLOBAL; return PASSED_LOCAL-only stages as mismatches.

    This is the full-state server-push reconciliation path (server hands back the set of
    confirmed stages); the runtime loop's evidence-driven upgrade uses `sync.background_reverify`
    instead. Both honor flag-not-rollback. Mismatches are flagged (returned), never force-rolled-back. §7.
    """
    mismatches: list[int] = []
    for i, status in enumerate(progress.statuses):
        if i in server_passed:
            mark_passed_global(progress, i)
        elif status is StageStatus.PASSED_LOCAL:
            mismatches.append(i)
    return mismatches
