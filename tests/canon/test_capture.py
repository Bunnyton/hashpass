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


@pytest.mark.tier1
def test_capture_symlink_is_a_link_to_its_resolved_target_however_spelled(tmp_path):
    """The links task: a symlink is observed as WHERE it points (any spelling), never as a copy."""
    home = tmp_path / "home" / "student"
    (home / "d" / "d").mkdir(parents=True)
    (home / "d" / "d" / "f.txt").write_text("x", encoding="utf-8")
    (home / "rel").symlink_to("d/d/f.txt")
    (home / "abs").symlink_to("/home/student/d/d/f.txt")      # absolute INSIDE the student's system
    (home / "dot").symlink_to("./d/../d/d/f.txt")
    (home / "dirlink").symlink_to("d/d")
    (home / "copy").write_text("x", encoding="utf-8")
    (home / "d" / "moved").symlink_to("d/d/f.txt")              # relative link moved: now broken
    keys = ["home/student/" + n for n in ("rel", "abs", "dot", "dirlink", "copy", "d/moved")]
    obs = capture(tmp_path, keys)
    want = FileState("link", "/home/student/d/d/f.txt")
    assert obs["home/student/rel"] == obs["home/student/abs"] == obs["home/student/dot"] == want
    assert obs["home/student/dirlink"] == FileState("link", "/home/student/d/d")   # not expanded
    assert obs["home/student/copy"] == FileState("file", "x")
    assert obs["home/student/d/moved"] == FileState("link", "/home/student/d/d/d/f.txt")


@pytest.mark.tier1
def test_capture_hard_linked_file_differs_from_a_copy(tmp_path):
    (tmp_path / "notes.txt").write_text("todo", encoding="utf-8")
    (tmp_path / "backup.txt").hardlink_to(tmp_path / "notes.txt")
    (tmp_path / "copy.txt").write_text("todo", encoding="utf-8")
    obs = capture(tmp_path, ["notes.txt", "backup.txt", "copy.txt"])
    assert obs["notes.txt"] == obs["backup.txt"] == FileState("hardlink", "todo")
    assert obs["copy.txt"] == FileState("file", "todo")
