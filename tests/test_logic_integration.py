import pytest

from hashpass.cmd import Cmd
from hashpass.compare import accept
from hashpass.hooks import HookRegistry


@pytest.mark.tier1
def test_filter_then_compare_accepts_within_threshold():
    r = HookRegistry()

    @r.filter(stages=None)
    def drop_timestamp(_cmd: str, data: str, _stage: int) -> str:
        return "\n".join(line.split(" ", 1)[-1] for line in data.splitlines())

    ref = r.run_filter("ls", "10:00 a\n10:00 b", 0)
    got = r.run_filter("ls", "11:59 a\n12:00 b", 0)
    assert ref == got
    assert accept(ref, got, mode="line", k=1, threshold=1.0, size_threshold=4096)


@pytest.mark.tier1
def test_check_hook_uses_cmd_normalization():
    r = HookRegistry()

    @r.check(stages=None)
    def wants_recursive_rm(cmd: str, _stage: int) -> bool | None:
        c = Cmd(cmd)
        if c.basecmd == "rm" and c.has_flag("-r"):
            return True
        return None

    assert r.run_check("rm -rf /tmp/x", 0) is True
    assert r.run_check("sudo rm -r /tmp/x", 0) is True
    assert r.run_check("rm /tmp/x", 0) is None
