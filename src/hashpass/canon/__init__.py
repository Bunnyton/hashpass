"""Differential canonicalization + tolerant matching against a canonical invariant."""
from hashpass.canon.capture import FileState, Observation, capture
from hashpass.canon.differential import canonicalize, derive_canonical
from hashpass.canon.noise import default_noise, run_noise
from hashpass.compare import similarity

__all__ = [
    "FileState",
    "Observation",
    "canonicalize",
    "capture",
    "default_noise",
    "derive_canonical",
    "matches",
    "run_noise",
]


def matches(
    canonical: Observation,
    candidate: Observation,
    *,
    threshold: float = 1.0,
    mode: str = "line",
    k: int = 1,
) -> bool:
    for key, want in canonical.items():
        got = candidate.get(key)
        if got is None or got.kind != want.kind:
            return False
        if want.kind == "file":
            if want.text is None or got.text is None:
                if want.text != got.text:
                    return False
            elif similarity(want.text, got.text, mode=mode, k=k) < threshold:
                return False
    return True
