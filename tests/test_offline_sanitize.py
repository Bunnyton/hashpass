"""
Tier1: the offline bundle's copy of the pool carries tasks and courses, nothing about people.

The bundle (scripts/offline) goes to strangers' machines: accounts, progress, enrollments, uploads in
flight, other authors' namespaces, course members and access requests must stay behind.
"""
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "offline" / "sanitize.py"


def _sanitize() -> ModuleType:
    spec = importlib.util.spec_from_file_location("offline_sanitize", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _put(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.tier1
def test_the_copy_keeps_tasks_and_courses_and_drops_people(tmp_path) -> None:
    snap, out = tmp_path / "registry", tmp_path / "pool"
    store = snap / "store"
    _put(snap / "users.json", {"users": {"bob": {}}})
    _put(snap / "progress" / "bob.json", {})
    _put(snap / "config.json", {"registration_open": False, "default_course": "bunnyton/linux"})
    _put(snap / "catalog.json", {"blocks": [{"id": "b", "name": "B", "tasks": [
        {"name": "bunnyton/ls", "version": "1"}, {"name": "bob/lab", "version": "1"}]}]})
    _put(store / "bunnyton" / "ls" / "1" / "meta.json", {"name": "bunnyton/ls"})
    _put(store / "bob" / "lab" / "1" / "meta.json", {"name": "bob/lab"})
    _put(store / "approved" / "bunnyton" / "ls" / "x.json", {})
    _put(store / ".repos" / "bunnyton" / "ls" / "repo.json", {"tags": {}, "members": {"bob": "author"}})
    _put(store / ".courses" / "bunnyton" / "linux" / "course.json", {
        "id": "c", "owner": "bunnyton", "name": "linux", "invite": "secret",
        "members": {"bob": "member"}, "requests": [{"user": "eve"}], "proposals": [{"by": "bob"}],
        "history": [{"by": "bob"}],
        "blocks": [{"id": "b", "tasks": [{"repo": "bunnyton/ls", "tag": "1"}, {"repo": "bob/lab", "tag": "1"}]}]})
    _put(store / ".enrollments" / "bob.json", {})
    _put(store / ".staging" / "x" / "intent.json", {})

    assert _sanitize().main([str(snap), str(out)]) == 0

    assert (out / "store" / "bunnyton" / "ls" / "1" / "meta.json").is_file()
    assert (out / "store" / "approved" / "bunnyton" / "ls" / "x.json").is_file()
    for gone in ("users.json", "progress", "store/bob", "store/.enrollments", "store/.staging"):
        assert not (out / gone).exists(), gone
    course = json.loads((out / "store/.courses/bunnyton/linux/course.json").read_text(encoding="utf-8"))
    assert (course["members"], course["requests"], course["proposals"], course["invite"], course["history"]) \
        == ({}, [], [], "", [])
    assert course["blocks"][0]["tasks"] == [{"repo": "bunnyton/ls", "tag": "1"}]
    repo = json.loads((out / "store/.repos/bunnyton/ls/repo.json").read_text(encoding="utf-8"))
    assert repo["members"] == {}
    catalog = json.loads((out / "catalog.json").read_text(encoding="utf-8"))
    assert [t["name"] for t in catalog["blocks"][0]["tasks"]] == ["bunnyton/ls"]
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert config == {"registration_open": True, "default_course": "bunnyton/linux"}
