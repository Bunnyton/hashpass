"""Runtime student loop: invisible check + local advance + hints + background re-verify (§7)."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from hashpass.canon import FileState, Observation, capture
from hashpass.grade import grade_stage
from hashpass.hints import StuckState, match_hint
from hashpass.progress import TaskProgress, current_stage, mark_passed_local
from hashpass.sync import SyncClient, background_reverify
from hashpass.taskcode.bundle import Bundle
from hashpass.taskcode.derive import StageChecks
from hashpass.taskcode.execute import OUTPUT_KEY

if TYPE_CHECKING:
    from hashpass.evidence import Evidence


def _elapsed_seconds(start_ts: str, now_ts: str) -> float:
    """Seconds between two ISO-8601 timestamps (used for the T-seconds stuck trigger)."""
    return (datetime.fromisoformat(now_ts) - datetime.fromisoformat(start_ts)).total_seconds()


def capture_candidate(rootfs: Path, checks: StageChecks, last_output: str) -> Observation:
    """
    Rebuild a comparable candidate from the student's live rootfs + last command output.

    Captures only the file-path keys of the canonical (OUTPUT_KEY excluded), then folds the
    student's last stdout in under OUTPUT_KEY. `matches` reads only canonical keys.
    """
    observe = [key for key in checks.canonical if key != OUTPUT_KEY]
    candidate = capture(rootfs, observe)
    candidate[OUTPUT_KEY] = FileState("file", last_output)
    return candidate


@dataclass
class FeedResult:
    """Outcome of feeding one command event through the invisible check + hints."""

    advanced: bool
    stage: int | None
    local_key: str | None
    hint: str | None


class PlaySession:
    """Drive one task's runtime loop: invisible check, local advance, hints, re-verify."""

    def __init__(self, bundle: Bundle, progress: TaskProgress, *,
                 student_id: str, nonce: str) -> None:
        """Start a play session over a task's bundle + mutable progress."""
        self.bundle = bundle
        self.progress = progress
        self.student_id = student_id
        self.nonce = nonce
        self.evidences: dict[int, Evidence] = {}
        self.stuck = StuckState()
        self._last_progress_ts: str | None = None

    def feed(self, *, command: str, rootfs: Path, last_output: str,
             ts: str, hooks=None) -> FeedResult:
        """Invisibly check the current stage; on accept advance locally + issue a local key."""
        if self._last_progress_ts is None:
            self._last_progress_ts = ts
        stage = current_stage(self.progress)
        advanced = False
        local_key = None
        if stage is not None:
            checks = self.bundle.checks.stages[stage]
            candidate = capture_candidate(rootfs, checks, last_output)
            grade = grade_stage(checks, candidate, task_id=self.bundle.checks.task_id,
                                stage=stage, student_id=self.student_id, nonce=self.nonce,
                                ts=ts, hooks=hooks)
            if grade.accepted:
                self.evidences[stage] = grade.evidence
                mark_passed_local(self.progress, stage)
                self.stuck = StuckState()
                self._last_progress_ts = ts
                advanced = True
                local_key = grade.local_key
            else:
                self.stuck.commands_since_progress += 1
                self.stuck.seconds_since_progress = _elapsed_seconds(self._last_progress_ts, ts)
        hint = match_hint(self.bundle.hints.get(stage, []), command=command,
                          output=last_output, stuck=self.stuck)
        return FeedResult(advanced=advanced, stage=stage, local_key=local_key, hint=hint)

    def reverify(self, sync: SyncClient) -> list[int]:
        """Background up-verification of provisional local passes against the server. §7."""
        return background_reverify(self.progress, self.evidences, self.bundle.checks, sync)
