"""Tier1: task data under content/tasks/<id>/data/ is real, committed and reproducible."""
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASKS = sorted(p for p in (ROOT / "content" / "tasks").iterdir() if (p / "Taskfile").is_file())
DATA = [t / "data" for t in TASKS if (t / "data").is_dir()]


def _mkdata() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "mkdata", ROOT / ".claude" / "skills" / "task-authoring" / "scripts" / "mkdata.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.tier1
def test_task_data_is_never_gitignored():
    # A stray `build/`-style ignore silently drops fixture files: a clone then builds a
    # different image than the author (find-2 lost six files at its answer depth).
    out = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--",
                          *[str(d.relative_to(ROOT)) for d in DATA]],
                         check=True, capture_output=True, text=True, cwd=ROOT).stdout
    assert out.strip() == "", f"ignored fixture files:\n{out}"


@pytest.mark.tier1
@pytest.mark.parametrize("data", DATA, ids=[d.parent.name for d in DATA])
def test_task_data_has_no_empty_directories(data: Path):
    # git cannot store an empty directory, so it would vanish on a clone; an intentionally
    # empty directory is made by `run mkdir -p` in the Taskfile instead.
    empty = [p.relative_to(data) for p in data.rglob("*") if p.is_dir() and not any(p.iterdir())]
    assert empty == [], f"empty dirs (git drops them): {empty}"


@pytest.mark.tier1
def test_mkdata_tree_leaves_no_directory_empty(tmp_path):
    mk = _mkdata()
    mk.main(["tree", str(tmp_path / "t"), "--seed", "3", "--depth", "5", "--dirs", "40", "--files", "5",
             "--plant", "a/b/keep/"])
    empty = [p for p in (tmp_path / "t").rglob("*") if p.is_dir() and not any(p.iterdir())]
    assert empty == []
    assert (tmp_path / "t" / "a" / "b" / "keep").is_dir()


@pytest.mark.tier1
def test_mkdata_tree_refuses_a_non_empty_target(tmp_path):
    # Re-running into an existing tree must not silently merge two generations.
    mk = _mkdata()
    mk.main(["tree", str(tmp_path / "t"), "--seed", "1", "--dirs", "3", "--files", "3"])
    with pytest.raises(SystemExit, match="not empty"):
        mk.main(["tree", str(tmp_path / "t"), "--seed", "2", "--dirs", "3", "--files", "3"])


@pytest.mark.tier1
def test_mkdata_never_names_a_directory_after_a_gitignore_pattern():
    mk = _mkdata()
    ignored = {"build", "dist", "__pycache__", ".venv"}
    assert not ignored & set(mk.DIR_NAMES)
