"""
Tier1: the find task accepts the right files however the path is written and wherever find ran.

The steps accept by `observe output` (settings similarity 100): the engine makes the paths in both
the reference (from `solve`) and the student's output absolute, then compares the SETS of lines --
so order does not matter either. This drives exactly that: `absolutize` + `matches`.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from hashpass.canon import FileState, matches
from hashpass.paths import absolutize

TASK = Path(__file__).resolve().parents[2] / "content" / "tasks" / "find"
REFERENCE = {   # the solve of each step, relative to the student's home
    "grade-depth": ["search", "-maxdepth", "3"],
    "grade-level3": ["search", "-mindepth", "3", "-maxdepth", "3", "-type", "f"],
    "grade-level4": ["search", "-type", "d", "-name", "level4*"],
    "grade-or": ["search", "-type", "f", "(", "-name", "level2*", "-o", "-name", "*3*", ")"],
    "grade-nonempty": ["search", "-type", "f", "-not", "-empty"],
}

# (expected, step, run from: h = ~ / s = ~/search / d = deeper, find arguments). User, 2026-10-13:
# «это должно автоматически учитываться, варианты путей — фигня».
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
    (False, "grade-nonempty", "h", [".", "-type", "f", "-not", "-empty"]),   # + ~/.bashrc: not in search
    (False, "grade-nonempty", "s", [".", "-type", "f"]),
    # deeper than search, paths going up (`..`): only readable with the command's directory
    (True, "grade-level4", "d", ["..", "-type", "d", "-name", "level4*"]),
    (True, "grade-nonempty", "d", ["..", "-type", "f", "-not", "-empty"]),
    (False, "grade-nonempty", "d", [".", "-type", "f", "-not", "-empty"]),
]

@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    h = tmp_path_factory.mktemp("root") / "home" / "student"
    h.mkdir(parents=True)
    shutil.copytree(TASK / "data" / "search", h / "search")
    (h / ".bashrc").write_text("# a real home has dotfiles\n", encoding="utf-8")
    return h


def _absolute_output(home: Path, cwd: Path, argv: list[str]) -> str:
    out = subprocess.run(["find", *argv], cwd=cwd, capture_output=True, text=True, check=False).stdout
    return absolutize(out, cwd=str(cwd), exists=lambda p: Path(p).exists(), home=str(home))


@pytest.mark.tier1
@pytest.mark.parametrize(("ok", "grade", "where", "args"), CASES)
def test_find_grade(home: Path, ok: bool, grade: str, where: str, args: list[str]) -> None:  # noqa: FBT001
    cwd = {"h": home, "s": home / "search", "d": next((home / "search").glob("level1_*"))}[where]
    argv = [a.replace("{H}", str(home)) for a in args]
    want = _absolute_output(home, home, REFERENCE[grade])
    got = _absolute_output(home, cwd, argv)
    accepted = matches({"<output>": FileState("file", want)}, {"<output>": FileState("file", got)},
                       threshold=1.0, mode="line", k=1)
    assert accepted is ok, f"{grade} from {where}: find {' '.join(argv)}"


@pytest.mark.tier1
def test_find_steps_accept_by_strict_observe_output() -> None:
    text = (TASK / "Taskfile").read_text(encoding="utf-8")
    assert "check exec" not in text
    assert text.count("\n  observe output\n") == len(REFERENCE)
    assert "similarity 100" in text
