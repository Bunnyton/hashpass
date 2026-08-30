import pytest

from hashpass.hooks import HookRegistry


@pytest.mark.tier1
def test_command_check_filter_dispatch():
    r = HookRegistry()

    @r.command(stages=None)
    def block_grep(cmd: str, _stage: int) -> dict:
        if cmd.split(maxsplit=1)[0] == "grep":
            return {"before": ["echo blocked"], "cmd": [], "after": []}
        return {"before": [], "cmd": [cmd], "after": []}

    assert r.run_command("grep x", 0) == {"before": ["echo blocked"], "cmd": [], "after": []}
    assert r.run_command("ls -la", 0) == {"before": [], "cmd": ["ls -la"], "after": []}

    @r.filter(stages=[0])
    def strip_size(_cmd: str, data: str, _stage: int) -> str:
        return data.replace("SIZE", "")

    assert r.run_filter("ls", "aSIZEb", 0) == "ab"
    assert r.run_filter("ls", "aSIZEb", 1) == "aSIZEb"

    @r.check(stages=None)
    def accept_ls(cmd: str, _stage: int) -> bool | None:
        if cmd == "ls":
            return True
        return None

    assert r.run_check("ls", 0) is True
    assert r.run_check("pwd", 0) is None
