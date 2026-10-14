"""Tier1: `accept cmd` names the command the student RAN (anchored), and `ok` needs exit 0."""
import pytest

from hashpass.taskrun import _accepted_by_cmd, _command_gates
from hashpass.taskstore import StageMeta


def _stage(*patterns: str, ok: bool = False) -> StageMeta:
    return StageMeta(message="m", neutral=(), check=None, on_enter=(), on_pass=(),
                     acceptance="command", accept_cmds=patterns, accept_ok=ok)


@pytest.mark.tier1
@pytest.mark.parametrize(("pattern", "command", "expected"), [
    ("cmatrix", "cmatrix", True),
    ("cmatrix", "sudo cmatrix -s", True),
    ("cmatrix", "ls | cmatrix", True),                 # segment split (feed() path sees the line)
    ("cmatrix", "/usr/games/cmatrix", True),           # a path counts by its basename
    ("sl", "/usr/games/sl", True),
    ("cmatrix", "./cmatrix -s", True),
    ("cmatrix", "dpkg -s cmatrix", False),             # mentions it, does not run it
    ("cmatrix", "ls cmatrix_2.0-3_amd64.deb", False),
    ("cmatrix", "rm cmatrix*.deb", False),
    ("sl", "sl -l", True),
    ("sl", "sleep 600 &", False),                      # word boundary, not a prefix
    ("ls --help", "ls --help | head", True),
    ("ls --help", "ls --color=auto --help", True),     # alias from a fresh user's ~/.bashrc
    ("grep -r ERROR", "grep --color=auto -r ERROR /var/log", True),
    ("apt update", "apt --fix-broken update", True),   # options may sit anywhere
    ("apt-get update", "sudo apt-get -y update", True),
    ("ls --help", "ls --hepl", False),
    ("ls --help", "ls", False),
    ("man man", "man manpages", False),
    ("apt update", "apt search update", False),         # positional words: exactly, in order
    ("apt update", "apt install update", False),
    ("man man", "man ls man", False),
    ("man man", "man man", True),
    ("apt update", "sudo apt update", True),
    ("apt-get update", "sudo -E apt-get update", True),
    ("apt install ./", "sudo apt install ./cmatrix_2.0-3_amd64.deb", True),   # `/` ends: prefix
    ("dpkg -i", "sudo dpkg -i ./x.deb", True),
    ("dpkg -i", "dpkg -install", False),
    ("grep -r ERROR", "sudo grep -r ERROR /var/log", True),
    ("cat notes", "sudo -u bob cat notes", True),        # sudo options that take an argument
    ("cat notes", "sudo -u bob -H cat notes", True),
    ("cat notes", "sudo -ubob cat notes", True),
    ("cat notes", "LANG=C cat notes", True),              # env assignments before the command
    ("cat notes", "sudo LANG=C cat notes", True),
    ("bob", "sudo -u bob cat notes", False),
    ("apt update", "sudo -R /srv/jail apt update", True),
])
def test_accept_cmd_is_anchored_on_the_command_actually_run(pattern, command, expected):
    assert _accepted_by_cmd(_stage(pattern), command, None) is expected


@pytest.mark.tier1
def test_accept_cmd_ok_requires_exit_zero_but_tolerates_an_unknown_status():
    ok = _stage("cmatrix", ok=True)
    assert _accepted_by_cmd(ok, "cmatrix", 0) is True
    assert _accepted_by_cmd(ok, "cmatrix", 127) is False       # died on a missing library
    assert _accepted_by_cmd(ok, "cmatrix", None) is True        # older console: status unknown
    plain = _stage("telnet")
    assert _accepted_by_cmd(plain, "telnet telehack.com", 1) is True   # no `ok`: failure counts


@pytest.mark.tier1
def test_accept_pattern_may_spell_sudo_too():
    """`accept cmd "sudo rm -rf /"` -- the pattern's own sudo is dropped like the command's."""
    from hashpass.taskrun import _cmd_matches  # noqa: PLC0415
    assert _cmd_matches("sudo rm -rf /", "sudo rm -rf /")
    assert _cmd_matches("sudo apt update", "sudo apt update")
    assert not _cmd_matches("sudo rm -rf /", "sudo ls -la /")   # positional words still must match


_FILES = {"/etc/os-release", "/etc/hostname", "/etc", "/var"}


@pytest.mark.tier1
@pytest.mark.parametrize(("command", "cwd", "expected"), [
    ("cat /etc/os-release", "/", True),
    ("cat os-release", "/etc", True),                  # root-tour 2026-10-14: refused before
    ("cat ./os-release", "/etc", True),
    ("cat ../etc/os-release", "/var", True),
    ("cat os-release", "/var", False),                 # a different file
    ("cat /etc/hostname", "/etc", False),
])
def test_accept_cmd_compares_path_arguments_as_files(command, cwd, expected):
    """A path in `accept cmd` names a FILE: any spelling of it from the student's cwd counts."""
    assert _accepted_by_cmd(_stage("cat /etc/os-release"), command, 0, cwd=cwd,
                            exists=_FILES.__contains__) is expected


@pytest.mark.tier1
def test_accept_cmd_relative_pattern_resolves_from_the_student_cwd():
    assert _accepted_by_cmd(_stage("cat os-release"), "cat /etc/os-release", 0, cwd="/etc",
                            exists=_FILES.__contains__)
    assert not _accepted_by_cmd(_stage("apt update"), "apt /update", 0, cwd="/",
                                exists=_FILES.__contains__)        # no such file: words differ


def _gated(*, cmds: tuple[str, ...] = (), texts: tuple = (), acceptance: str = "command") -> StageMeta:
    return StageMeta(message="m", neutral=(), check=None, on_enter=(), on_pass=(),
                     acceptance=acceptance, accept_cmds=cmds, accept_texts=texts)


@pytest.mark.tier1
def test_command_gates_output_and_file_patterns():
    files = {"/home/student/.vimrc": 'set nu\nnnoremap <F2> Iprint(data["<Esc>A"])<Esc>j\n'}
    gate = _gated(texts=(("output", "Терпение должны"),))
    assert _command_gates(gate, "cat x", 0, "…\nТерпение должны иметь мы\n", read=files.get) is True
    assert _command_gates(gate, "cat x", 0, "реклама\n", read=files.get) is False
    vim = _gated(texts=(("/home/student/.vimrc", r"^\s*:?n?(nore)?map\s"),))
    assert _command_gates(vim, "vim f", 0, "", read=files.get) is True
    assert _command_gates(vim, "vim f", 0, "", read={}.get) is False            # no ~/.vimrc yet
    empty = _gated(cmds=("chatterbox.sh",), texts=(("output", None),))
    assert _command_gates(empty, "./chatterbox.sh > /dev/null 2>&1", 0, "\n", read={}.get) is True
    assert _command_gates(empty, "./chatterbox.sh > /dev/null", 0, "boo\n", read={}.get) is False
    assert _command_gates(empty, "ls > /dev/null", 0, "", read={}.get) is False


@pytest.mark.tier1
def test_command_gates_are_none_without_command_checks():
    assert _command_gates(_gated(acceptance="derived"), "x", 0, "", read={}.get) is None
