"""
Tier1: a task never relies on what the course has not taught yet.

User, 2026-10-09: «в 3-м задании сразу идёт | grep, а pipe они не проходили». The course order is
`BLOCKS` in content/tasks/deploy.sh; each shell concept below is taught by one task. Every task
BEFORE it must not show the concept to the student (brief, say/hint text) nor need it for its main
`solve`. A `variant` (another accepted way) may use anything -- it is never shown.
"""
import re
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"

# concept -> (the task that teaches it, how its use looks in a command)
CONCEPTS = {
    "пайп |": ("pipes", re.compile(
        r"\S\s*(?<!\|)\|(?!\|)\s*(?:sudo\s+)?"
        r"(?:grep|less|more|wc|sort|uniq|head|tail|tee|cat|awk|sed|cut|tr|xargs)\b")),
    "перенаправление >": ("inventory", re.compile(r"[\w'\"]\s*>>?\s*[~/\w][\w./-]*")),
}
_SAY = re.compile(r'\bsay(?:\s+dramatic)?\s+"((?:[^"\\]|\\.)*)"')
_SOLVE = re.compile(r"^\s*solve:?\s+(.*)$")


def course_order() -> list[str]:
    """Task ids in course order, from the BLOCKS array of deploy.sh."""
    text = (CONTENT / "deploy.sh").read_text(encoding="utf-8")
    body = text.split("BLOCKS=(", 1)[1].split("\n)", 1)[0]
    return [t for line in re.findall(r"'([^']*)'", body) for t in line.split(":", 1)[1].split()]


def _visible_and_solve(task: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in (CONTENT / task / "Taskfile").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        out += [("say/hint", m.group(1)) for m in _SAY.finditer(line)]
        if m := _SOLVE.match(line):
            out.append(("solve", m.group(1)))
    for md in sorted((CONTENT / task).glob("*.md")):
        if md.name.lower() != "readme.md":
            out += [(md.name, ln) for ln in md.read_text(encoding="utf-8").splitlines()
                    if not ln.lstrip().startswith(">")]          # a markdown quote, not a redirect
    return out


@pytest.mark.tier1
def test_teaching_tasks_are_in_the_course():
    order = course_order()
    for concept, (teacher, _rx) in CONCEPTS.items():
        assert teacher in order, f"{concept}: урок {teacher} не стоит в BLOCKS deploy.sh"


@pytest.mark.tier1
@pytest.mark.parametrize("concept", list(CONCEPTS))
def test_no_task_uses_a_concept_before_it_is_taught(concept):
    order = course_order()
    teacher, rx = CONCEPTS[concept]
    bad = [f"{task} ({where}): {text.strip()}"
           for task in order[:order.index(teacher)]
           for where, text in _visible_and_solve(task) if rx.search(text)]
    assert not bad, (f"{concept} раньше урока «{teacher}»:\n  " + "\n  ".join(bad))
