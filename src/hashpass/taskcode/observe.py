"""Classify observed keys as stable/pruned across runs, and apply exclude curation."""
from dataclasses import dataclass

from hashpass.canon import Observation


@dataclass(frozen=True)
class ObserveClassification:
    """Split of observed keys into stable (kept) vs pruned (incidental)."""

    stable: tuple[str, ...]
    pruned: tuple[str, ...]


def classify_observed(observations: list[Observation]) -> ObserveClassification:
    """
    Classify observed fields as stable or pruned across runs.

    A key is stable iff it appears in every observation and all values are equal.
    Otherwise it is pruned. Both tuples are sorted.
    """
    keys: set[str] = set().union(*(obs.keys() for obs in observations)) if observations else set()
    stable: list[str] = []
    pruned: list[str] = []
    for key in sorted(keys):
        values = [obs[key] for obs in observations if key in obs]
        if len(values) == len(observations) and all(v == values[0] for v in values):
            stable.append(key)
        else:
            pruned.append(key)
    return ObserveClassification(stable=tuple(stable), pruned=tuple(pruned))


def apply_curation(obs: Observation, *, exclude: tuple[str, ...]) -> Observation:
    """
    Drop keys matching any exclude prefix.

    Returns a new Observation with keys that match any prefix in exclude removed.
    """
    return {k: v for k, v in obs.items() if not any(k.startswith(p) for p in exclude)}
