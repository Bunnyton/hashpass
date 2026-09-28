"""Tier1: what the student reads never mentions hashpass internals (stages, graders, checks)."""
import re
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TASKS = sorted(p for p in CONTENT.iterdir() if (p / "Taskfile").is_file())

# The student lives in a world of files, commands and their output. Words of the ENGINE's
# world -- стадия/этап, грейдер, «засчитается»/«зачёт», the hidden /hp layer, the Taskfile,
# «baked in at build time» -- must not reach them (user rule 2026-09-28: «писать о стадиях
# или внутреннем устройстве hashpass нельзя»).
_FORBIDDEN = re.compile(
    r"стади|этап|грейдер|засчит|зач[её]т|\bTaskfile\b|(?<![\w/])/hp\b|build time|\bcopy`",
    re.IGNORECASE)
# `stage "…"`, `say "…"`, `say dramatic "…"`, and an unquoted `say …` to end of line.
_SAY = re.compile(r'\b(?:stage|say)(?:\s+dramatic)?\s+(?:"((?:[^"\\]|\\.)*)"|(\S.*))')
_USER_ROOT = re.compile(r"^\s*user\s+root\b", re.MULTILINE)
_ROOT_REASON = re.compile(r"^#\s*root:", re.MULTILINE)


def _shown_lines(text: str) -> str:
    """Drop a script's `#` comment lines -- they are never printed."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _student_texts(task: Path) -> list[tuple[str, str]]:
    """(where, text) for every string a student can see in this task."""
    out: list[tuple[str, str]] = []
    for line in (task / "Taskfile").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        out += [(f"{task.name}/Taskfile", m.group(1) or m.group(2)) for m in _SAY.finditer(line)]
    for f in sorted(task.rglob("*")):
        if not f.is_file() or f.name.lower() == "readme.md" or f.name == "Taskfile":
            continue                               # README is for authors; the Taskfile is parsed above
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue                               # a binary asset
        out.append((f"{task.name}/{f.relative_to(task)}", _shown_lines(text)))
    return out


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=[t.name for t in TASKS])
def test_student_facing_text_never_mentions_internals(task: Path):
    offenders = [f"{where}: …{text[max(0, m.start() - 30):m.end() + 30]!r}"
                 for where, text in _student_texts(task)
                 for m in [_FORBIDDEN.search(text)] if m]
    assert not offenders, "\n".join(offenders)


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=[t.name for t in TASKS])
def test_tasks_run_as_student_unless_a_reason_says_root(task: Path):
    # Rule (user, 2026-09-28): tasks go «по максимуму от другого пользователя» -- the default
    # `student` + sudo. `settings user root` needs a `# root: <why>` line in the Taskfile.
    text = (task / "Taskfile").read_text(encoding="utf-8")
    if _USER_ROOT.search(text):
        assert _ROOT_REASON.search(text), f"{task.name}: `user root` without a `# root: …` reason"
