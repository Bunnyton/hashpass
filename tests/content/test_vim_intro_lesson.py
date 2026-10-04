"""Tier1: vim-intro -- the silent «opened in vim» stage and the visible «every ---> line fixed» check."""
import subprocess
from pathlib import Path

import pytest

_TASK = Path(__file__).resolve().parents[2] / "content" / "tasks" / "vim-intro"
_FIXED = [
    "Сделай каждую строку со стрелкой такой же, как строка под ней.", "",
    "---> Мышь в норке тихо грызёт сыр.", "     Мышь в норке тихо грызёт сыр.", "",
    "---> Рыжий кот на тёплом окне сладко жмурится.",
    "     Рыжий кот на тёплом окне сладко жмурится.", "",
    "---> Без труда не выловишь и рыбку из пруда.", "     Без труда не выловишь и рыбку из пруда.",
]


def _lesson(tmp_path: Path, lines: list[str]) -> bool:
    f = tmp_path / "lesson1.txt"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return subprocess.run(["sh", str(_TASK / "hp" / "lesson"), "cat lesson1.txt", str(f)],
                          check=False).returncode == 0


def _invim(command: str) -> bool:
    return subprocess.run(["sh", str(_TASK / "hp" / "invim"), command, "/home/student/lesson1.txt"],
                          check=False).returncode == 0


@pytest.mark.tier1
@pytest.mark.parametrize("command", [
    "vim lesson1.txt", "vi ~/lesson1.txt", "sudo vim /home/student/lesson1.txt", "vim ./lesson1.txt",
])
def test_opening_the_file_in_vim_passes_the_silent_stage(command):
    assert _invim(command)


@pytest.mark.tier1
@pytest.mark.parametrize("command", ["sed -i s/a/b/ lesson1.txt", "vim other.txt", "vimtutor", "", "cat lesson1.txt"])
def test_other_commands_do_not(command):
    assert not _invim(command)


@pytest.mark.tier1
def test_fixed_lines_pass(tmp_path):
    assert _lesson(tmp_path, _FIXED)


@pytest.mark.tier1
def test_trailing_spaces_are_forgiven(tmp_path):
    assert _lesson(tmp_path, [ln + "  " if ln.startswith("--->") else ln for ln in _FIXED])


@pytest.mark.tier1
def test_the_shipped_exercise_is_not_already_solved(tmp_path):
    assert not _lesson(tmp_path, (_TASK / "data" / "lesson1.txt").read_text(encoding="utf-8").splitlines())


@pytest.mark.tier1
@pytest.mark.parametrize("lines", [
    [ln.replace("сладко ", "") if ln.startswith("--->") else ln for ln in _FIXED],
    [ln for ln in _FIXED if not ln.startswith("---> Без")],                       # arrow deleted
])
def test_unfixed_lines_fail(tmp_path, lines):
    assert not _lesson(tmp_path, lines)
