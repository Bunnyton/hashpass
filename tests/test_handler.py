from pathlib import Path

import pytest

from hashpass.handler import HandlerContext, HandlerResult, build_invocation, run_handler
from hashpass.image.base import build_base
from hashpass.recipe.model import ExecAction
from hashpass.runner.nspawn import NspawnRunner


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


def _hp(tmp_path, script_name, script_body) -> Path:
    hp = tmp_path / "hp"
    (hp / "work").mkdir(parents=True)
    s = hp / "work" / script_name
    s.write_text(script_body, encoding="utf-8")
    s.chmod(0o755)
    (hp / "state.json").write_text("{}", encoding="utf-8")
    return hp


@pytest.mark.tier3
def test_run_handler_file_echoes_argv_and_env(tmp_path, base_tar):
    hp = _hp(tmp_path, "say.sh", '#!/bin/sh\necho "cmd=$1 tries=$HP_TRIES"\n')
    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = NspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        ctx = HandlerContext(student_cmd="grep -i err log", tries=4, last_out="", stage=0)
        res = run_handler(r, ExecAction("say.sh"), ctx, hp_dir=hp)
        assert res.exit_code == 0
        assert res.stdout.strip() == "cmd=grep -i err log tries=4"
    finally:
        r.teardown()


@pytest.mark.tier3
def test_run_handler_command_predicate_exit_code(tmp_path, base_tar):
    hp = tmp_path / "hp"
    (hp / "work").mkdir(parents=True)
    (hp / "state.json").write_text("{}", encoding="utf-8")
    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = NspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        r.run(["sh", "-c", "printf 'ERROR here\\n' > /errors.txt"])
        ctx = HandlerContext(student_cmd="", tries=0, last_out="", stage=0)
        ok = run_handler(r, ExecAction("grep -q ERROR /errors.txt"), ctx, hp_dir=hp)
        assert ok.exit_code == 0
        no = run_handler(r, ExecAction("grep -q NOPE /errors.txt"), ctx, hp_dir=hp)
        assert no.exit_code != 0
    finally:
        r.teardown()


@pytest.mark.tier1
def test_hp_last_out_sanitized(work):
    ctx = HandlerContext(student_cmd="cat bin", tries=0, last_out="a\x00b\x00c", stage=0)
    _, env = build_invocation(ExecAction("grep x f"), ctx, hp_work_host=work)
    assert env["HP_LAST_OUT"] == "abc"
    assert "\x00" not in env["HP_LAST_OUT"]


@pytest.mark.tier1
def test_hp_last_out_bounded(work):
    ctx = HandlerContext(student_cmd="c", tries=0, last_out="Z" * 200000, stage=0)
    _, env = build_invocation(ExecAction("grep x f"), ctx, hp_work_host=work)
    assert len(env["HP_LAST_OUT"]) == 65536  # noqa: PLR2004


@pytest.mark.tier1
def test_handler_result_stderr_defaults_empty():
    assert HandlerResult(stdout="x", exit_code=0).stderr == ""
    assert HandlerResult(stdout="x", exit_code=1, stderr="boom").stderr == "boom"
