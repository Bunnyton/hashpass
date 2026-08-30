"""Sync port + in-process server model + background re-verification of provisional progress (§7)."""
from dataclasses import dataclass
from typing import Protocol

from hashpass.evidence import Evidence
from hashpass.progress import StageStatus, TaskProgress, mark_passed_global
from hashpass.server.verify import issue_global_key
from hashpass.taskcode.derive import DerivedChecks, StageChecks


class SyncClient(Protocol):
    """Client-held handle to the server: reachability + a submit that may sign one stage."""

    def online(self) -> bool: ...
    def submit(self, evidence: Evidence, checks: StageChecks) -> str | None: ...


@dataclass
class LocalSyncClient:
    """In-process model of the SERVER side (holds the secret). Dev/test only, never shipped."""

    server_secret: bytes
    principal: str
    online_flag: bool = True

    def online(self) -> bool:
        """Whether the modeled server is reachable."""
        return self.online_flag

    def submit(self, evidence: Evidence, checks: StageChecks) -> str | None:
        """Bind principal to the claimed identity, then re-verify + sign (§6, Plan E #2)."""
        if evidence.student_id != self.principal:
            return None
        return issue_global_key(evidence, checks, server_secret=self.server_secret)


def background_reverify(progress: TaskProgress, evidences: dict[int, Evidence],
                        checks: DerivedChecks, sync: SyncClient) -> list[int]:
    """Upgrade correctly-passed local stages to global credit; flag the rest. Offline -> no-op. §7."""
    if not sync.online():
        return []
    mismatches: list[int] = []
    for stage in sorted(evidences):
        if progress.statuses[stage] is not StageStatus.PASSED_LOCAL:
            continue
        evidence = evidences[stage]
        if evidence.task_id != checks.task_id:   # never sign against the wrong task
            mismatches.append(stage)
            continue
        gkey = sync.submit(evidence, checks.stages[stage])   # pair checks by (task_id, stage)
        if gkey is not None:
            mark_passed_global(progress, stage)
        else:
            mismatches.append(stage)
    return mismatches
