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


@pytest.mark.tier1
def test_empty_canonical_rejects_all():
    assert not matches({}, {"a.txt": FileState(kind="file", text="anything\n")})
    assert not matches({}, {})


@pytest.mark.tier1
def test_matches_compares_link_targets_and_hardlink_content():
    link = {"l": FileState("link", "/home/student/f")}
    assert matches(link, {"l": FileState("link", "/home/student/f")})
    assert not matches(link, {"l": FileState("link", "/home/student/g")})
    assert not matches(link, {"l": FileState("file", "x")})          # a copy is not a link
    hard = {"b": FileState("hardlink", "todo\n")}
    assert matches(hard, {"b": FileState("hardlink", "todo\n")})
    assert not matches(hard, {"b": FileState("hardlink", "other\n")})
    assert not matches(hard, {"b": FileState("file", "todo\n")})


@pytest.mark.tier1
def test_strict_threshold_is_exact_even_for_large_outputs():
    """
    A strict `similarity 100` is EXACT, also past the 4 KiB MinHash switch.

    A find answer with one extra path (~/.bashrc) among thousands estimated at 1.0 by MinHash and
    passed as a "strict" match (2026-10-14).
    """
    lines = [f"/home/student/search/level1_{i:03d}/level2_x/file_{i:03d}.txt" for i in range(2000)]
    want = "\n".join(lines)
    assert len(want) > 4096  # noqa: PLR2004  (past the MinHash switch)
    got = want + "\n/home/student/.bashrc"
    canon = {"<output>": FileState("file", want)}
    assert matches(canon, {"<output>": FileState("file", want)}, threshold=1.0, mode="line", k=1)
    assert not matches(canon, {"<output>": FileState("file", got)}, threshold=1.0, mode="line", k=1)


@pytest.mark.tier1
def test_matches_perms_exactly():
    want = {"perms:t": FileState("perms", "0123 1000:1000")}
    assert matches(want, {"perms:t": FileState("perms", "0123 1000:1000")})
    assert not matches(want, {"perms:t": FileState("perms", "0133 1000:1000")})
    assert not matches(want, {"perms:t": FileState("perms", "0123 1000:1001")})
