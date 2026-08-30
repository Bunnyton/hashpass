"""Interactive hints: match a stage's triggers (command / output / stuck) to a message (§7)."""
from dataclasses import dataclass

_STUCK_CMDS = 5
_STUCK_SECS = 120.0


@dataclass
class StuckState:
    """Progress-less streak counters that drive the 'stuck' hint trigger (§7)."""

    commands_since_progress: int = 0
    seconds_since_progress: float = 0.0


def match_hint(hints_for_stage: list[dict], *, command: str, output: str,  # noqa: PLR0913
               stuck: StuckState, stuck_cmds: int = _STUCK_CMDS,
               stuck_secs: float = _STUCK_SECS) -> str | None:
    """
    Return the first matching hint's message (list order), else None. §7.

    Trigger kinds, checked command -> output -> stuck:
      {"command": <substr>} fires when substr is in command;
      {"output": <substr>}  fires when substr is in output;
      {"stuck": true}       fires when commands_since_progress >= stuck_cmds
                            or seconds_since_progress >= stuck_secs.
    """
    stuck_now = (stuck.commands_since_progress >= stuck_cmds
                 or stuck.seconds_since_progress >= stuck_secs)
    for hint in hints_for_stage:
        trigger = hint.get("trigger", {})
        if (("command" in trigger and trigger["command"] in command)
                or ("output" in trigger and trigger["output"] in output)
                or (bool(trigger.get("stuck")) and stuck_now)):
            return hint["message"]
    return None
