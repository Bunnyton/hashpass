import pytest

from hashpass.cmd import Cmd, parse_cmds


@pytest.mark.tier1
def test_cmd_parse_eq_contains_similar():
    c = Cmd("sudo rm -rf /tmp/x")
    assert c.is_sudo
    assert c.basecmd == "rm"
    assert c.short_flags == {"r", "f"}
    assert c.args == ["/tmp/x"]  # noqa: S108
    assert c.has_flag("-r")
    assert c.has_flag("-f")
    assert not c.has_flag("--force")

    assert Cmd("ls -la") == Cmd("ls -la")
    assert Cmd("ls -la") != Cmd("ls -l")
    assert Cmd("rm -r") in Cmd("rm -rf /tmp/x")
    assert Cmd("rm -z") not in Cmd("rm -rf /tmp/x")
    assert Cmd("grep -i foo").is_similar(Cmd("grep -i bar"))
    assert not Cmd("grep -i foo").is_similar(Cmd("grep foo"))


@pytest.mark.tier1
def test_parse_cmds_splits():
    cmds = parse_cmds("apt update && apt install sl ; echo done")
    assert [c.basecmd for c in cmds] == ["apt", "apt", "echo"]
