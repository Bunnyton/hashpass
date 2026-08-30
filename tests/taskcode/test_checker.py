import pytest

from hashpass.canon import FileState
from hashpass.hooks import HookRegistry
from hashpass.taskcode.checker import check_conditions, check_stage
from hashpass.taskcode.derive import StageChecks


def _checks(text: str) -> StageChecks:
    return StageChecks(canonical={"result.txt": FileState("file", text)}, mode="line")


@pytest.mark.tier1
def test_check_stage_accepts_correct_rejects_wrong():
    checks = _checks("answer\n")
    assert check_stage(checks, {"result.txt": FileState("file", "answer\n")})
    assert not check_stage(checks, {"result.txt": FileState("file", "WRONG\n")})
    assert not check_stage(checks, {})   # missing stable field → reject


@pytest.mark.tier1
def test_check_stage_check_hook_true_short_circuits():
    hooks = HookRegistry()

    @hooks.check()
    def _c(_cmd, _stage) -> bool:
        return True

    checks = _checks("answer\n")
    # candidate would FAIL matches, but @check True overrides (§4 escape)
    assert check_stage(checks, {"result.txt": FileState("file", "WRONG\n")},
                       hooks=hooks, probe_cmd="anything")


@pytest.mark.tier1
def test_check_stage_check_hook_none_defers_to_matches():
    hooks = HookRegistry()

    @hooks.check()
    def _c(_cmd, _stage) -> None:
        return None

    checks = _checks("answer\n")
    assert check_stage(checks, {"result.txt": FileState("file", "answer\n")}, hooks=hooks)
    assert not check_stage(checks, {"result.txt": FileState("file", "WRONG\n")}, hooks=hooks)


@pytest.mark.tier1
def test_check_conditions_deny_require_flags_mention():
    assert check_conditions({"deny": ["rm"]}, ["ls -l"])
    assert not check_conditions({"deny": ["rm"]}, ["rm -rf /"])        # denied command
    assert check_conditions({"require_flags": ["-l"], "mention": ["sort"]},
                            ["ls -l", "sort file"])
    assert not check_conditions({"require_flags": ["-l"]}, ["ls"])     # missing flag
    assert not check_conditions({"mention": ["sort"]}, ["ls -l"])      # missing mention
