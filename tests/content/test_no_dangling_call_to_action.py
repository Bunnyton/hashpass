"""Tier1: a task never ends on an order -- the last step's `on pass` states, it does not ask."""
import re
from pathlib import Path

import pytest

from hashpass.recipe.model import SayAction
from tests.content.recipes import is_task_dir, parse_task

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TASKS = sorted(p for p in CONTENT.iterdir() if is_task_dir(p))

# User, 2026-10-12, the fifth time (cd-abs, cp-basics, cp-more, inventory, pipes): «рано
# переходит», «опять двадцать пять». The finale prints right after the last step's `on pass`; an
# order there («повтори с >> и загляни в файл», «вернись — там тебя кое-что ждёт», «попробуй на
# dir3») is never checked, so the task looks cut short. Something to DO is a step of its own.
_ORDER = re.compile(
    r"\b(?:спроси|повтори|попробуй|добавь|допиши|сделай|загляни|вернись|набери|введи|запусти|выполни|"
    r"открой|найди|создай|удали|скопируй|перенеси|нажми|поставь|напиши|проверь|посмотри|"
    r"а теперь)\b", re.IGNORECASE)


@pytest.mark.tier1
@pytest.mark.parametrize("task", TASKS, ids=lambda p: p.name)
def test_last_step_on_pass_gives_no_order(task: Path) -> None:
    recipe = parse_task(task)
    if not recipe.stages:
        return
    said = [a.text for a in recipe.stages[-1].on_pass if isinstance(a, SayAction)]
    orders = [t for t in said if _ORDER.search(t)]
    assert not orders, f"{task.name}: the finale follows at once -- make it a step or a fact: {orders}"
