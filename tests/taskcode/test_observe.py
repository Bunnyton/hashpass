import pytest

from hashpass.canon import FileState
from hashpass.taskcode.observe import apply_curation, classify_observed


@pytest.mark.tier1
def test_classify_observed_splits_stable_and_pruned():
    const = FileState("file", "answer")
    obs = [
        {"a": const, "t": FileState("file", "1")},
        {"a": const, "t": FileState("file", "2")},
        {"a": const, "t": FileState("file", "3")},
    ]
    result = classify_observed(obs)
    assert result.stable == ("a",)   # present & equal in all runs
    assert result.pruned == ("t",)   # varied → pruned


@pytest.mark.tier1
def test_classify_observed_prunes_key_absent_in_some_run():
    const = FileState("file", "answer")
    obs = [{"a": const, "b": const}, {"a": const}]   # "b" absent in 2nd run
    result = classify_observed(obs)
    assert result.stable == ("a",)
    assert result.pruned == ("b",)


@pytest.mark.tier1
def test_apply_curation_drops_excluded_prefixes():
    obs = {"keep.txt": FileState("file", "k"), "tmp/x": FileState("file", "t")}
    out = apply_curation(obs, exclude=("tmp/",))
    assert "keep.txt" in out
    assert "tmp/x" not in out
