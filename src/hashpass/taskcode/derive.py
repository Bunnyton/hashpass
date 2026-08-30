"""Differential derivation of per-stage acceptance checks (canonical + pinned comparator)."""
from collections.abc import Callable
from dataclasses import dataclass

from hashpass.canon import Observation, canonicalize
from hashpass.runner.base import Runner
from hashpass.taskcode.execute import OUTPUT_KEY, run_stage
from hashpass.taskcode.model import TaskCode

_MIN_K = 2


@dataclass(frozen=True)
class StageChecks:
    """Derived acceptance check for one stage: canonical invariant + pinned comparator."""

    canonical: Observation
    mode: str = "line"
    threshold: float = 1.0
    k: int = 1
    size_threshold: int = 4096


@dataclass(frozen=True)
class DerivedChecks:
    """All per-stage derived checks for a task."""

    task_id: str
    stages: tuple[StageChecks, ...]


def _has_signal(canonical: Observation) -> bool:
    """Return whether a canonical Observation carries a real discriminating signal."""
    if any(k != OUTPUT_KEY for k in canonical):     # any observed FS field is a real signal
        return True
    out = canonical.get(OUTPUT_KEY)
    return out is not None and bool(out.text)       # a non-empty output is a signal; empty is not


def derive_checks(runner_factory: Callable[[], Runner], task: TaskCode, *,  # noqa: PLR0913
                  passes: int = 3, mode: str = "line", threshold: float = 1.0,
                  noise: list[list[str]] | None = None) -> DerivedChecks:
    """
    Derive per-stage checks by running each stage multiple times and canonicalizing.

    Args:
        runner_factory: Callable that returns a fresh prepared Runner for each call.
        task: TaskCode describing the stages to run.
        passes: Number of times to run each stage (must be >= _MIN_K).
        mode: Comparator mode for similarity matching (e.g., "line").
        threshold: Comparator threshold for similarity matching.
        noise: Optional noise commands to run between stages.

    Returns:
        DerivedChecks with per-stage canonical invariants and pinned comparator parameters.

    Raises:
        ValueError: If passes < _MIN_K, or a stage's canonical is vacuous (no stable signal).

    """
    if passes < _MIN_K:
        msg = "passes must be >= 2 for differential derivation"
        raise ValueError(msg)
    stage_checks: list[StageChecks] = []
    for stage_index in range(len(task.stages)):
        observations: list[Observation] = []
        for _ in range(passes):
            runner = runner_factory()
            try:
                observations.append(run_stage(runner, task, stage_index, noise=noise))
            finally:
                runner.teardown()
        canonical = canonicalize(observations)
        if not _has_signal(canonical):
            msg = f"stage {stage_index}: no stable discriminating signal (vacuous canonical)"
            raise ValueError(msg)
        stage_checks.append(StageChecks(canonical=canonical, mode=mode, threshold=threshold))
    return DerivedChecks(task_id=task.id, stages=tuple(stage_checks))
