import pytest

from hashpass.hints import StuckState, match_hint, match_rule
from hashpass.recipe.model import (
    CmdCond,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    SayAction,
    TriesCond,
)

_HINTS = [
    {"trigger": {"command": "rm -rf"}, "message": "careful with rm"},
    {"trigger": {"output": "Permission denied"}, "message": "you need sudo"},
    {"trigger": {"stuck": True}, "message": "try reading the task again"},
]
_STUCK_AT = 5
_SECS_AT = 120.0


@pytest.mark.tier1
def test_command_substring_trigger_fires():
    hint = match_hint(_HINTS, command="rm -rf /", output="", stuck=StuckState())
    assert hint == "careful with rm"


@pytest.mark.tier1
def test_output_substring_trigger_fires():
    hint = match_hint(_HINTS, command="cat x", output="cat: x: Permission denied",
                      stuck=StuckState())
    assert hint == "you need sudo"


@pytest.mark.tier1
def test_stuck_fires_at_threshold_by_commands_or_seconds():
    below = StuckState(commands_since_progress=_STUCK_AT - 1)
    assert match_hint(_HINTS, command="ls", output="", stuck=below) is None
    by_cmds = StuckState(commands_since_progress=_STUCK_AT)
    assert match_hint(_HINTS, command="ls", output="", stuck=by_cmds) == "try reading the task again"
    by_secs = StuckState(seconds_since_progress=_SECS_AT)
    assert match_hint(_HINTS, command="ls", output="", stuck=by_secs) == "try reading the task again"


@pytest.mark.tier1
def test_first_match_wins_in_list_order():
    hints = [
        {"trigger": {"command": "make"}, "message": "first"},
        {"trigger": {"command": "make"}, "message": "second"},
    ]
    assert match_hint(hints, command="make build", output="", stuck=StuckState()) == "first"


@pytest.mark.tier1
def test_no_match_returns_none():
    assert match_hint(_HINTS, command="ls", output="ok", stuck=StuckState()) is None


"""Validate the explicit-atom hint rule matcher (match_rule)."""

_NO = {"tries": 0, "idle": 0.0, "command": "", "output": ""}


@pytest.mark.tier1
def test_tries_and_idle_thresholds():
    rules = (HintRule(TriesCond(3), SayAction("t")),)
    assert match_rule(rules, **{**_NO, "tries": 2}) is None
    assert match_rule(rules, **{**_NO, "tries": 3}) == SayAction("t")
    idle_rules = (HintRule(IdleCond(90.0), SayAction("i")),)
    assert match_rule(idle_rules, **{**_NO, "idle": 89.9}) is None
    assert match_rule(idle_rules, **{**_NO, "idle": 90.0}) == SayAction("i")


@pytest.mark.tier1
def test_cmd_has_missing_and_output():
    rules = (HintRule(CmdCond("grep", (), ("-i",)), ExecAction("f.sh")),)
    assert match_rule(rules, **{**_NO, "command": "grep ERROR log"}) == ExecAction("f.sh")
    assert match_rule(rules, **{**_NO, "command": "grep -i ERROR log"}) is None  # missing -i present
    assert match_rule(rules, **{**_NO, "command": "cat log"}) is None            # wrong base
    has_rules = (HintRule(CmdCond("grep", ("-r",), ()), SayAction("h")),)
    assert match_rule(has_rules, **{**_NO, "command": "grep -r x ."}) == SayAction("h")
    assert match_rule(has_rules, **{**_NO, "command": "grep x ."}) is None
    out_rules = (HintRule(OutputCond("ERROR"), SayAction("o")),)
    assert match_rule(out_rules, **{**_NO, "output": "boom ERROR here"}) == SayAction("o")


@pytest.mark.tier1
def test_cmd_missing_and_has_match_words_not_just_flags():
    # `missing <word>` fires only when the word is truly absent (was always-firing when a bare word
    # went through has_flag). `has <word>` requires the word to be present as an argument.
    miss = (HintRule(CmdCond("echo", (), ("ГОТОВО",)), SayAction("m")),)
    assert match_rule(miss, **{**_NO, "command": "echo ГОТОВО"}) is None          # word present
    assert match_rule(miss, **{**_NO, "command": "echo nope"}) == SayAction("m")  # word absent
    has = (HintRule(CmdCond("echo", ("ГОТОВО",), ()), SayAction("h")),)
    assert match_rule(has, **{**_NO, "command": "echo ГОТОВО > f"}) == SayAction("h")
    assert match_rule(has, **{**_NO, "command": "echo other"}) is None


@pytest.mark.tier1
def test_first_match_wins_and_unparseable_command():
    rules = (
        HintRule(TriesCond(2), SayAction("first")),
        HintRule(TriesCond(1), SayAction("second")),
    )
    assert match_rule(rules, **{**_NO, "tries": 5}) == SayAction("first")
    cmd_rules = (HintRule(CmdCond("grep", (), ()), SayAction("c")),)
    assert match_rule(cmd_rules, **{**_NO, "command": 'echo "oops'}) is None  # shlex raises -> no match


@pytest.mark.tier1
def test_fired_rules_are_skipped_so_an_ascending_ladder_escalates_once_per_rung():
    # A hint ladder written in ascending order: question at 2 tries, pointer at 4. With `fired`
    # tracking, each rung fires exactly once and the lower rung never re-fires on later commands.
    rules = (
        HintRule(TriesCond(2), SayAction("question")),
        HintRule(TriesCond(4), SayAction("pointer")),
    )
    fired: set[int] = set()
    assert match_rule(rules, **{**_NO, "tries": 1}, fired=fired) is None
    assert match_rule(rules, **{**_NO, "tries": 2}, fired=fired) == SayAction("question")
    assert fired == {0}
    assert match_rule(rules, **{**_NO, "tries": 3}, fired=fired) is None      # rung 0 already fired
    assert match_rule(rules, **{**_NO, "tries": 4}, fired=fired) == SayAction("pointer")
    assert fired == {0, 1}
    assert match_rule(rules, **{**_NO, "tries": 9}, fired=fired) is None      # ladder exhausted


@pytest.mark.tier1
def test_match_rule_without_fired_keeps_repeating():
    # Backwards-compatible: no `fired` set -> stateless first-match, as before.
    rules = (HintRule(TriesCond(2), SayAction("again")),)
    assert match_rule(rules, **{**_NO, "tries": 2}) == SayAction("again")
    assert match_rule(rules, **{**_NO, "tries": 3}) == SayAction("again")
