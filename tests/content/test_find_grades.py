"""Tier1: the find task accepts the right files however the path is written and wherever find ran."""
import shutil
import subprocess
from pathlib import Path

import pytest

TASK = Path(__file__).resolve().parents[2] / "content" / "tasks" / "find"

# (expected, grade, run from: h = ~ / s = ~/search, find arguments). User, 2026-10-13: «это должно
# автоматически учитываться, варианты путей — фигня» -- `find . …` from ~ (with ., ./.bashrc in the
# output) or from ~/search, absolute or relative: only the files inside search count.
CASES = [
    (True, "grade-depth", "h", ["search", "-maxdepth", "3"]),
    (True, "grade-depth", "h", ["./search", "-maxdepth", "3"]),
    (True, "grade-depth", "h", ["{H}/search", "-maxdepth", "3"]),
    (True, "grade-depth", "h", [".", "-maxdepth", "4", "-path", "./search*"]),
    (True, "grade-depth", "s", [".", "-maxdepth", "3"]),
    (True, "grade-depth", "s", ["-maxdepth", "3"]),
    (False, "grade-depth", "h", ["search", "-maxdepth", "2"]),
    (False, "grade-depth", "s", [".", "-maxdepth", "4"]),
    (True, "grade-level3", "h", [".", "-mindepth", "4", "-maxdepth", "4", "-type", "f"]),
    (True, "grade-level3", "s", [".", "-mindepth", "3", "-maxdepth", "3", "-type", "f"]),
    (False, "grade-level3", "h", [".", "-mindepth", "3", "-maxdepth", "3", "-type", "f"]),
    (False, "grade-level3", "s", [".", "-mindepth", "3", "-maxdepth", "3"]),
    (True, "grade-level4", "h", [".", "-type", "d", "-name", "level4*"]),
    (False, "grade-level4", "s", [".", "-name", "level4*"]),
    (True, "grade-or", "h", [".", "-type", "f", "(", "-name", "level2*", "-o", "-name", "*3*", ")"]),
    (False, "grade-or", "s", [".", "-type", "f", "-name", "level2*", "-o", "-name", "*3*"]),
    (True, "grade-nonempty", "h", [".", "-type", "f", "-not", "-empty"]),
    (False, "grade-nonempty", "s", [".", "-type", "f"]),
]


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("root")
    h = root / "home" / "student"
    h.mkdir(parents=True)
    shutil.copytree(TASK / "data" / "search", h / "search")
    (h / ".bashrc").write_text("# a real home has dotfiles\n", encoding="utf-8")
    for g in (TASK / "hp").glob("grade-*"):
        (root / g.name).write_text(g.read_text(encoding="utf-8").replace("/home/student", str(h)),
                                   encoding="utf-8")
    return h


@pytest.mark.tier1
@pytest.mark.parametrize(("ok", "grade", "where", "args"), CASES)
def test_find_grade(home: Path, ok: bool, grade: str, where: str, args: list[str]) -> None:  # noqa: FBT001
    cwd = home if where == "h" else home / "search"
    argv = [a.replace("{H}", str(home)) for a in args]
    out = subprocess.run(["find", *argv], cwd=cwd, capture_output=True, text=True, check=False).stdout
    rc = subprocess.run(["sh", str(home.parent.parent / grade), "find -name " + " ".join(argv)],
                        env={"PATH": "/usr/bin:/bin", "HP_LAST_OUT": out}, check=False).returncode
    assert (rc == 0) is ok, f"{grade} from {where}: find {' '.join(argv)}"
