"""Differential canonicalization: keep only fields stable across all runs."""
from collections.abc import Callable

from hashpass.canon.capture import Observation

_MIN_K = 2


def canonicalize(observations: list[Observation]) -> Observation:
    if not observations:
        return {}
    first = observations[0]
    return {
        key: state
        for key, state in first.items()
        if all(key in obs and obs[key] == state for obs in observations)
    }


def derive_canonical(run_once: Callable[[], Observation], *, k: int = 3) -> Observation:
    if k < _MIN_K:
        msg = "k must be >= 2 for differential canonicalization"
        raise ValueError(msg)
    return canonicalize([run_once() for _ in range(k)])
