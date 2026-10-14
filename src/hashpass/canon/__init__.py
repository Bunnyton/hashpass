"""Differential canonicalization + tolerant matching against a canonical invariant."""
from hashpass.canon.capture import FileState, Observation, capture
from hashpass.canon.differential import canonicalize, derive_canonical
from hashpass.canon.noise import default_noise, run_noise
from hashpass.compare import shingle, similarity

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


def _same(want: FileState, got: FileState, *, threshold: float, mode: str, k: int) -> bool:
    """Whether one observed path matches its canonical state."""
    if got.kind != want.kind:
        return False
    if want.kind == "link":                              # where it points, exactly
        return got.text == want.text
    if want.kind not in ("file", "hardlink"):
        return True
    if want.text is None or got.text is None:
        return want.text == got.text
    if threshold >= 1.0:                                 # strict = exact, at any size: MinHash past
        return shingle(want.text, mode=mode, k=k) == shingle(got.text, mode=mode, k=k)   # 4 KiB missed a line
    return similarity(want.text, got.text, mode=mode, k=k) >= threshold


def matches(
    canonical: Observation,
    candidate: Observation,
    *,
    threshold: float = 1.0,
    mode: str = "line",
    k: int = 1,
) -> bool:
    if not canonical:
        return False
    for key, want in canonical.items():
        got = candidate.get(key)
        if got is None or not _same(want, got, threshold=threshold, mode=mode, k=k):
            return False
    return True
