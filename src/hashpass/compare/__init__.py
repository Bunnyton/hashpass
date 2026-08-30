"""Size-adaptive similarity: exact Jaccard for small inputs, MinHash for large."""
import hashlib

from hashpass.compare.minhash import minhash_jaccard, minhash_signature
from hashpass.compare.shingle import jaccard, shingle

__all__ = ["accept", "exact_hash", "jaccard", "shingle", "similarity"]


def similarity(a: str, b: str, *, mode: str = "word", k: int = 3,  # noqa: PLR0913
               size_threshold: int = 4096, num_perm: int = 128) -> float:
    if not a and not b:
        return 1.0
    sa, sb = shingle(a, mode=mode, k=k), shingle(b, mode=mode, k=k)
    if max(len(a), len(b)) <= size_threshold:
        return jaccard(sa, sb)
    return minhash_jaccard(minhash_signature(sa, num_perm=num_perm),
                           minhash_signature(sb, num_perm=num_perm))


def accept(a: str, b: str, *, threshold: float, **kw: object) -> bool:
    return similarity(a, b, **kw) >= threshold


def exact_hash(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
