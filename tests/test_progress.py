"""Tests for the per-stage progress state machine."""
import pytest

from hashpass.progress import (
    StageStatus,
    current_stage,
    mark_passed_global,
    mark_passed_local,
    new_progress,
    reconcile,
)


@pytest.mark.tier1
def test_new_progress_opens_first_stage_only():
    progress = new_progress("demo", 3)
    assert progress.task_id == "demo"
    assert progress.statuses == [StageStatus.OPEN, StageStatus.LOCKED, StageStatus.LOCKED]
    assert current_stage(progress) == 0


@pytest.mark.tier1
def test_mark_passed_local_advances_and_opens_next():
    progress = new_progress("demo", 2)
    mark_passed_local(progress, 0)
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL
    assert progress.statuses[1] is StageStatus.OPEN
    assert current_stage(progress) == 1
    mark_passed_local(progress, 1)
    assert current_stage(progress) is None  # all passed


@pytest.mark.tier1
def test_mark_passed_global_is_idempotent():
    progress = new_progress("demo", 1)
    mark_passed_local(progress, 0)
    mark_passed_global(progress, 0)
    mark_passed_global(progress, 0)
    assert progress.statuses[0] is StageStatus.PASSED_GLOBAL


@pytest.mark.tier1
def test_reconcile_upgrades_confirmed_and_flags_local_only_without_rollback():
    progress = new_progress("demo", 3)
    mark_passed_local(progress, 0)  # server will confirm
    mark_passed_local(progress, 1)  # server will NOT confirm -> mismatch
    mismatches = reconcile(progress, {0})
    assert mismatches == [1]
    assert progress.statuses[0] is StageStatus.PASSED_GLOBAL   # upgraded
    assert progress.statuses[1] is StageStatus.PASSED_LOCAL    # flagged, NOT rolled back
    assert progress.statuses[2] is StageStatus.OPEN
