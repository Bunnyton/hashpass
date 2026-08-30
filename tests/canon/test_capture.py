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
