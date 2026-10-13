"""Tier1: generic hints are rare -- the scripted ones (a natural error, a dose) do the talking."""
import re
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TASKS = sorted(p for p in CONTENT.iterdir() if (p / "Taskfile").is_file())
# User, 2026-10-12: «очень часто подсказки бесят, нужно сделать реже (только если они не заложены в
# сценарий, ключи и т.д.)». `hint output` / `hint cmd` (a reaction to the student's own mistake) stay;
# the generic ladder starts at the 5th failed try, and «долгая пауза» (idle) hints are gone.
MIN_TRIES = 5
_TRIES = re.compile(r"^\s*hint tries (\d+)", re.MULTILINE)
_IDLE = re.compile(r"^\s*hint idle\b", re.MULTILINE)


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=lambda p: p.name)
def test_generic_hints_are_rare(task: Path) -> None:
    text = (task / "Taskfile").read_text(encoding="utf-8")
    assert not _IDLE.search(text), f"{task.name}: no idle hints"
    early = [int(n) for n in _TRIES.findall(text) if int(n) < MIN_TRIES]
    assert not early, f"{task.name}: hint tries below {MIN_TRIES}: {early}"
