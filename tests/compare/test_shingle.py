import pytest

from hashpass.compare.shingle import jaccard, shingle


@pytest.mark.tier1
def test_shingle_modes_and_jaccard():
    assert shingle("abcd", mode="char", k=2) == frozenset({"ab", "bc", "cd"})
    assert shingle("a b c", mode="word", k=2) == frozenset({"a b", "b c"})
    assert shingle("x\n\ny", mode="line") == frozenset({"x", "y"})

    assert jaccard(frozenset(), frozenset()) == 1.0
    assert jaccard({"a"}, set()) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
