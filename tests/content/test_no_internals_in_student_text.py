"""Tier1: what the student reads never mentions hashpass internals (stages, graders, checks)."""
import re
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TASKS = sorted(p for p in CONTENT.iterdir() if (p / "Taskfile").is_file())

# The student lives in a world of files, commands and their output. Words of the ENGINE's
# world -- стадия/этап, грейдер, «засчитается», the hidden /hp layer, the Taskfile -- must not
# reach them (user rule 2026-09-28: «писать о стадиях или внутреннем устройстве hashpass нельзя»).
_FORBIDDEN = re.compile(r"стади[яиюе]|этап|грейдер|засчит|зачт[её]н|\bTaskfile\b|(?<![\w/])/hp\b",
                        re.IGNORECASE)
_QUOTED = re.compile(r'\b(?:say|stage)\s+"((?:[^"\\]|\\.)*)"')


def _student_texts(task: Path) -> list[tuple[str, str]]:
    """(where, text) for every string a student can see in this task."""
    out: list[tuple[str, str]] = []
    for line in (task / "Taskfile").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        out += [(f"{task.name}/Taskfile", m.group(1)) for m in _QUOTED.finditer(line)]
    for md in sorted(task.glob("*.md")) + sorted((task / "hp").glob("*.md")):
        if md.name.lower() == "readme.md":        # author-facing notes, never shown to students
            continue
        out.append((f"{task.name}/{md.relative_to(task)}", md.read_text(encoding="utf-8")))
    finale = task / "hp" / "finale"
    if finale.is_file():                      # a shell script: its `#` comment lines are never shown
        shown = "\n".join(ln for ln in finale.read_text(encoding="utf-8").splitlines()
                          if not ln.lstrip().startswith("#"))
        out.append((f"{task.name}/hp/finale", shown))
    return out


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=[t.name for t in TASKS])
def test_student_facing_text_never_mentions_internals(task: Path):
    offenders = [f"{where}: …{text[max(0, m.start() - 30):m.end() + 30]!r}"
                 for where, text in _student_texts(task)
                 for m in [_FORBIDDEN.search(text)] if m]
    assert not offenders, "\n".join(offenders)
