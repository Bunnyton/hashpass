"""Tier1: vim-intro's check -- every ---> line fixed to its sample AND the file was edited in vim."""
import os
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


def _lesson(tmp_path: Path, lines: list[str], history: list[str]) -> bool:
    f = tmp_path / "lesson1.txt"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    hist = tmp_path / "history"
    hist.write_text("".join(h + "\n" for h in history), encoding="utf-8")
    env = {**os.environ, "HP_HISTORY": str(hist)}
    return subprocess.run(["sh", str(_TASK / "hp" / "lesson"), history[-1] if history else "", str(f)], env=env,
                          check=False).returncode == 0


@pytest.mark.tier1
@pytest.mark.parametrize("history", [
    ["vim lesson1.txt"], ["vimtutor ru", "vi ~/lesson1.txt"], ["sudo vim /home/student/lesson1.txt"],
])
def test_fixed_in_vim_passes(tmp_path, history):
    assert _lesson(tmp_path, _FIXED, history)


@pytest.mark.tier1
def test_trailing_spaces_are_forgiven(tmp_path):
    lines = [ln + "  " if ln.startswith("--->") else ln for ln in _FIXED]
    assert _lesson(tmp_path, lines, ["vim lesson1.txt"])


@pytest.mark.tier1
def test_the_shipped_exercise_is_not_already_solved(tmp_path):
    raw = (_TASK / "data" / "lesson1.txt").read_text(encoding="utf-8").splitlines()
    assert not _lesson(tmp_path, raw, ["vim lesson1.txt"])


@pytest.mark.tier1
@pytest.mark.parametrize(("lines", "history"), [
    (_FIXED, ["sed -i 's/x/y/' lesson1.txt"]),                    # fixed, but not in vim
    (_FIXED, []),
    ([ln.replace("сладко ", "") if ln.startswith("--->") else ln for ln in _FIXED], ["vim lesson1.txt"]),
    ([ln for ln in _FIXED if not ln.startswith("---> Без")], ["vim lesson1.txt"]),   # arrow deleted
])
def test_unfixed_or_not_in_vim_is_silently_refused(tmp_path, lines, history):
    assert not _lesson(tmp_path, lines, history)
