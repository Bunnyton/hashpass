"""Interactive hints: match a stage's triggers (command / output / stuck) to a message (§7)."""
from dataclasses import dataclass

from hashpass.cmd import Cmd
from hashpass.recipe.model import (
    Action,
    CmdCond,
    Condition,
    HintRule,
    IdleCond,
    OutputCond,
    TriesCond,
)

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


def _cmd_matches(cond: CmdCond, command: str) -> bool:
    """Return True if the command has base `cond.base` with the required/forbidden flags."""
    try:
        cmd = Cmd(command)
    except ValueError:
        return False  # an unparseable typo never satisfies a cmd condition
    if cmd.basecmd != cond.base:
        return False
    return (all(cmd.has_flag(f) for f in cond.has)
            and not any(cmd.has_flag(f) for f in cond.missing))


def _cond_matches(cond: Condition, *, tries: int, idle: float,
                  command: str, output: str) -> bool:
    """Evaluate one explicit condition atom against the current session context (§7.1)."""
    if isinstance(cond, TriesCond):
        return tries >= cond.n
    if isinstance(cond, IdleCond):
        return idle >= cond.seconds
    if isinstance(cond, CmdCond):
        return _cmd_matches(cond, command)
    if isinstance(cond, OutputCond):
        return cond.substr in output
    msg = f"unknown condition: {cond!r}"
    raise TypeError(msg)


def match_rule(rules: tuple[HintRule, ...], *, tries: int, idle: float,
               command: str, output: str) -> Action | None:
    """
    Return the action of the first hint rule whose condition matches, else None (§7.1).

    Conditions are explicit atoms (`tries`/`idle`/`cmd`/`output`); first-match-wins in
    source order. `tries` is neutral-excluded; `idle` is seconds since last progress.
    """
    for rule in rules:
        if _cond_matches(rule.condition, tries=tries, idle=idle,
                         command=command, output=output):
            return rule.action
    return None
