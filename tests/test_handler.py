import pytest

from hashpass.handler import HandlerContext, HandlerResult, build_invocation
from hashpass.recipe.model import ExecAction


@pytest.fixture
def work(tmp_path):
    (tmp_path / "verify.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "seed.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return tmp_path


@pytest.mark.tier1
def test_file_handler_argv_and_env(work):
    ctx = HandlerContext(student_cmd="grep -i ERROR log", tries=3, last_out="l1\nl2", stage=1)
    argv, env = build_invocation(ExecAction("verify.sh"), ctx, hp_work_host=work)
    assert argv == ["/hp/work/verify.sh", "grep -i ERROR log"]
    assert env["HP_TRIES"] == "3"
    assert env["HP_LAST_OUT"] == "l1\nl2"
    assert env["HP_STAGE"] == "1"
    assert env["HP_STATE"] == "/hp/state.json"
    assert env["HP_ROOTFS"] == "/"
    assert [k for k in env if k.startswith("HP_ARG_")] == []


@pytest.mark.tier1
def test_file_handler_named_and_positional_args(work):
    ctx = HandlerContext(student_cmd="cmd", tries=0, last_out="", stage=0)
    argv, env = build_invocation(
        ExecAction('verify.sh expected="a b" mode=strict'), ctx, hp_work_host=work)
    assert argv == ["/hp/work/verify.sh", "cmd"]
    assert env["HP_ARG_expected"] == "a b"
    assert env["HP_ARG_mode"] == "strict"
    argv2, _ = build_invocation(ExecAction("verify.sh strict"), ctx, hp_work_host=work)
    assert argv2 == ["/hp/work/verify.sh", "cmd", "strict"]


@pytest.mark.tier1
def test_command_handler_falls_through_to_sh_c(work):
    ctx = HandlerContext(student_cmd="cmd", tries=2, last_out="", stage=0)
    argv, env = build_invocation(ExecAction("grep -q ERROR errors.txt"), ctx, hp_work_host=work)
    assert argv == ["sh", "-c", "grep -q ERROR errors.txt"]
    assert env["HP_TRIES"] == "2"


@pytest.mark.tier1
def test_empty_action_raises(work):
    ctx = HandlerContext(student_cmd="cmd", tries=0, last_out="", stage=0)
    with pytest.raises(ValueError, match="empty exec"):
        build_invocation(ExecAction("   "), ctx, hp_work_host=work)


@pytest.mark.tier1
def test_handler_result_is_a_value():
    assert HandlerResult(stdout="hi", exit_code=0).exit_code == 0
