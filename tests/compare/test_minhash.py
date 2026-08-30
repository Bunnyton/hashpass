import pytest

from hashpass.compare.minhash import minhash_jaccard, minhash_signature
from hashpass.compare.shingle import jaccard, shingle


@pytest.mark.tier1
def test_minhash_estimates_jaccard():
    a = shingle(" ".join(str(i) for i in range(200)), mode="word", k=2)
    b = shingle(" ".join(str(i) for i in range(100, 300)), mode="word", k=2)
    sa = minhash_signature(a, num_perm=256)
    sb = minhash_signature(b, num_perm=256)
    assert minhash_signature(a, num_perm=256) == sa
    assert minhash_jaccard(sa, sa) == 1.0
    assert abs(minhash_jaccard(sa, sb) - jaccard(a, b)) < 0.1  # noqa: PLR2004


@pytest.mark.tier1
def test_minhash_length_mismatch_raises():
    with pytest.raises(ValueError, match="length"):
        minhash_jaccard((1, 2), (1, 2, 3))


@pytest.mark.tier1
def test_minhash_empty_edges():
    # empty vs non-empty signatures → 0.0
    assert minhash_jaccard(minhash_signature(set()), minhash_signature({"a", "b"})) == 0.0
    # empty signatures short-circuit → 1.0
    assert minhash_jaccard((), ()) == 1.0
