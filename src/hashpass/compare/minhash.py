"""Pure-stdlib MinHash signatures + Jaccard estimate."""
import hashlib

_MAX = (1 << 64) - 1


def _h(shingle: str, i: int) -> int:
    digest = hashlib.sha1(f"{i}:{shingle}".encode()).digest()  # noqa: S324
    return int.from_bytes(digest[:8], "big")


def minhash_signature(shingles: set[str] | frozenset[str], *, num_perm: int = 128) -> tuple[int, ...]:
    if not shingles:
        return tuple(_MAX for _ in range(num_perm))
    return tuple(min(_h(s, i) for s in shingles) for i in range(num_perm))


def minhash_jaccard(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
    if len(sig_a) != len(sig_b):
        msg = "signature length mismatch"
        raise ValueError(msg)
    if not sig_a:
        return 1.0
    return sum(1 for x, y in zip(sig_a, sig_b, strict=True) if x == y) / len(sig_a)
