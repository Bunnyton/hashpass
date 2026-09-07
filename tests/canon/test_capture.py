import pytest

from hashpass.canon.capture import FileState, capture


@pytest.mark.tier1
def test_capture_files_dirs_and_output(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "b.txt").write_text("world", encoding="utf-8")
    (tmp_path / "out").write_text("OUT", encoding="utf-8")

    obs = capture(tmp_path, ["a.txt", "d", "missing.txt"], output_path="out")
    assert obs["a.txt"] == FileState("file", "hello")
    assert obs["d/b.txt"] == FileState("file", "world")
    assert obs["missing.txt"] == FileState("absent", None)
    assert obs["<output>"] == FileState("file", "OUT")


@pytest.mark.tier1
def test_capture_bool_observe_is_existence_kind_only(tmp_path):
    # `observe bool`: capture KIND only -- no content, and NO recursion into a directory.
    (tmp_path / "f.txt").write_text("some content", encoding="utf-8")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "child").write_text("x", encoding="utf-8")
    obs = capture(tmp_path, [], bool_observe=["f.txt", "d", "gone"])
    assert obs["f.txt"] == FileState("file", None)      # content dropped
    assert obs["d"] == FileState("dir", None)           # the dir itself, not its children
    assert "d/child" not in obs                         # no recursion
    assert obs["gone"] == FileState("absent", None)
