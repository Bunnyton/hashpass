import pytest

from hashpass.compare import accept, exact_hash, similarity


@pytest.mark.tier1
def test_similarity_small_path_exact_jaccard():
    assert similarity("a b c", "a b c", size_threshold=4096) == 1.0
    assert similarity("a b c d", "a b c e", mode="word", k=1, size_threshold=4096) == pytest.approx(3 / 5)
    assert similarity("", "", size_threshold=4096) == 1.0


@pytest.mark.tier1
def test_similarity_large_path_uses_minhash():
    big_a = " ".join(str(i) for i in range(2000))
    big_b = " ".join(str(i) for i in range(1000, 3000))
    s = similarity(big_a, big_b, mode="word", k=2, size_threshold=100, num_perm=256)
    assert 0.2 < s < 0.45  # noqa: PLR2004


@pytest.mark.tier1
def test_accept_threshold_and_exact_hash():
    assert accept("a b c", "a b x", mode="word", k=1, threshold=0.3, size_threshold=4096)
    assert not accept("a b c", "x y z", mode="word", k=1, threshold=0.3, size_threshold=4096)
    assert exact_hash("hi") == exact_hash("hi")
    assert exact_hash("hi") != exact_hash("ho")
