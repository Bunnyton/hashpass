import pytest

from hashpass.canon import FileState, matches


@pytest.mark.tier1
def test_matches_checks_only_canonical_fields():
    canon = {"result.txt": FileState("file", "answer")}
    # candidate matches the stable field, plus has an extra volatile field (ignored)
    ok = {"result.txt": FileState("file", "answer"), "time.txt": FileState("file", "999")}
    assert matches(canon, ok)
    # wrong stable field → reject
    bad = {"result.txt": FileState("file", "WRONG")}
    assert not matches(canon, bad)
    # missing stable field → reject
    assert not matches(canon, {})


@pytest.mark.tier1
def test_matches_tolerant_threshold():
    canon = {"out": FileState("file", "a\nb\nc")}
    close = {"out": FileState("file", "a\nb\nX")}
    assert matches(canon, close, mode="line", k=1, threshold=0.5)
    assert not matches(canon, close, mode="line", k=1, threshold=0.6)
