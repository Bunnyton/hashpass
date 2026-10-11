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


@pytest.mark.tier1
def test_has_flag_knows_find_style_single_dash_words():
    """`find -mindepth`/`-type`: a long single-dash option is a word, not a bundle of letters."""
    c = Cmd("find search -mindepth 3 -maxdepth 3")
    assert c.has_flag("-mindepth") and c.has_flag("-maxdepth")
    assert not c.has_flag("-type")
    assert Cmd("rm -rf dir").has_flag("-rf") and Cmd("rm -fr dir").has_flag("-rf")   # bundles
    assert Cmd("ls -la").has_flag("-l") and not Cmd("ls -la").has_flag("-t")
