"""Tier1: a plain stage that only tracks the path -- same goal as the next one, prints nothing."""
from types import SimpleNamespace

import pytest

from hashpass import cli
from hashpass.taskrun import FeedResult

_GOAL = "Выставь файлу test1 права --x--x--x"


def _session(state: dict, messages: list[str]) -> SimpleNamespace:
    def observe(command, *, ts, output, rc=None) -> FeedResult:  # noqa: ARG001
        state["stage"] += 1                       # the command passes the path stage
        return FeedResult(advanced=True, stage=state["stage"] - 1, local_key="")

    def check_current(*, ts) -> FeedResult:      # noqa: ARG001
        state["stage"] += 1                       # ...and already reached the result stage
        return FeedResult(advanced=True, stage=state["stage"] - 1, local_key="")

    return SimpleNamespace(progress=object(),
                           meta=SimpleNamespace(stages=[SimpleNamespace(message=m) for m in messages]),
                           observe=observe, check_current=check_current, enter=lambda: None,
                           enter_stage=lambda: None, fire_outro=lambda: None)


@pytest.mark.tier1
def test_the_same_goal_twice_in_a_row_is_announced_once(monkeypatch):
    state = {"stage": 0}
    messages = [_GOAL, _GOAL, "Дальше"]
    session = _session(state, messages)
    monkeypatch.setattr(cli, "current_stage",
                        lambda _p: state["stage"] if state["stage"] < len(messages) else None)
    shown: list[str] = []
    io = cli.Io(read=lambda _p: None, write=shown.append, clock=lambda: "t")
    cli._announce_stage(session, io)                                   # noqa: SLF001
    cli._render_observe(session, "chmod +x test1", "", None, 0, io)    # noqa: SLF001
    text = "".join(shown)
    assert text.count(_GOAL) == 1                    # the path stage did not repeat the goal
    assert state["stage"] == messages.index("Дальше") and "Дальше" in text   # the same command was graded for stage 2 at once
