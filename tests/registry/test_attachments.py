"""Tier1: the per-image attachment store (description + files, path-safe)."""
import pytest

from hashpass.registry.attachments import AttachmentStore, safe_filename


@pytest.mark.tier1
def test_description_and_files_roundtrip(tmp_path):
    store = AttachmentStore(tmp_path)
    assert store.describe("lab:1") == {"description": "", "files": []}
    store.set_description("lab:1", "Лабораторная 1")
    store.put_file("lab:1", "Taskfile", b"stage ...", taskfile=True)
    hint = "подсказка".encode()
    store.put_file("lab:1", "hint.txt", hint)
    info = store.describe("lab:1")
    assert info["description"] == "Лабораторная 1"
    names = {f["name"]: f for f in info["files"]}
    assert set(names) == {"Taskfile", "hint.txt"}
    assert names["Taskfile"]["taskfile"] is True
    assert names["hint.txt"]["size"] == len(hint)
    assert store.read_file("lab:1", "Taskfile") == b"stage ..."


@pytest.mark.tier1
def test_delete_file(tmp_path):
    store = AttachmentStore(tmp_path)
    store.put_file("ns/app:2", "a.txt", b"x")
    assert store.delete_file("ns/app:2", "a.txt") is True
    assert store.describe("ns/app:2")["files"] == []
    assert store.delete_file("ns/app:2", "a.txt") is False


@pytest.mark.tier1
def test_isolated_by_ref(tmp_path):
    store = AttachmentStore(tmp_path)
    store.put_file("a:1", "f", b"1")
    store.put_file("b:1", "f", b"2")
    assert store.read_file("a:1", "f") == b"1"
    assert store.read_file("b:1", "f") == b"2"


@pytest.mark.tier1
def test_safe_filename_strips_paths_and_rejects_traversal():
    assert safe_filename("/etc/passwd") == "passwd"
    assert safe_filename("a/b/c.txt") == "c.txt"
    assert safe_filename("Task File (1).hp") == "Task File (1).hp"
    for bad in ("..", "", "   ", "\x00"):
        with pytest.raises(ValueError, match="файл"):
            safe_filename(bad)


@pytest.mark.tier1
def test_ref_path_safety(tmp_path):
    store = AttachmentStore(tmp_path)
    for bad in ("../evil:1", "..:1", "a/../../x:1"):
        with pytest.raises(ValueError, match=r"образ|версия"):
            store.put_file(bad, "f", b"x")
