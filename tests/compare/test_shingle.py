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


@pytest.mark.tier1
def test_line_mode_ignores_insignificant_characters():
    # mc task, 2026-10-23: a password copied off the screen with the mouse carries trailing
    # spaces; mcedit/Windows editors add \r, a BOM or a zero-width space -- none of it is the answer.
    want = shingle("walrus-6610\n", mode="line")
    for got in ("walrus-6610", "walrus-6610   ", "  walrus-6610\t\n", "walrus-6610\r\n",
                "\ufeffwalrus-6610", "walrus-6610\u200b", "\u00a0walrus-6610\u00a0", "\n\nwalrus-6610\n\n"):
        assert shingle(got, mode="line") == want, repr(got)


@pytest.mark.tier1
def test_line_mode_squeezes_inner_whitespace_but_keeps_words():
    # ls -l pads its columns to the widest entry: the same link reads "  20 Oct" or " 34 Oct".
    assert shingle("a   b\tc", mode="line") == shingle("a b c", mode="line")
    assert shingle("ab", mode="line") != shingle("a b", mode="line")
    assert shingle("walrus-6610", mode="line") != shingle("walrus-6611", mode="line")
