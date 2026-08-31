import re
from pathlib import Path

import pytest

from hashpass.runner.base import RunResult
from hashpass.runner.booted import _capture_files, _handler_lowers, _machine_name


@pytest.mark.tier1
def test_capture_files_parses_rc_and_passes_streams_verbatim():
    assert _capture_files("out\n", "err\n", "0") == RunResult("out\n", "err\n", 0)
    assert _capture_files("", "", "2").exit_code == 2      # noqa: PLR2004
    assert _capture_files("", "", "127").exit_code == 127  # noqa: PLR2004
    assert _capture_files("", "", "").exit_code == 1          # missing rc -> sentinel
    assert _capture_files("", "", "  \n").exit_code == 1      # blank rc -> sentinel
    assert _capture_files("", "", "0\n").exit_code == 0       # trailing newline stripped
    assert _capture_files("", "", "boot-failed").exit_code == 1  # garbage -> sentinel
    assert _capture_files("data", "warn", "0").stdout == "data"   # stdout verbatim
    assert _capture_files("data", "warn", "0").stderr == "warn"   # stderr verbatim
    assert _capture_files("", "", "3").stdout == ""              # empty stdout preserved
    assert isinstance(_capture_files("", "", "0").exit_code, int)


@pytest.mark.tier1
def test_machine_name_is_valid_and_unique():
    name = _machine_name()
    assert name.startswith("hp-")
    assert re.fullmatch(r"hp-[0-9a-f]{12}", name) is not None
    assert len(name) == 15                       # noqa: PLR2004
    assert len(name) <= 64                        # noqa: PLR2004
    assert name[0] != "-" and name[-1] != "-"
    assert len({_machine_name() for _ in range(2000)}) == 2000  # noqa: PLR2004


@pytest.mark.tier1
def test_handler_lowers_stack_order():
    up, l1, l2, base = Path("/up"), Path("/l1"), Path("/l2"), Path("/base")
    res = _handler_lowers(up, [l1, l2], base)
    assert res[0] == up                          # live booted upper on top
    assert res[-1] == base                        # base at bottom
    assert res[1:-1] == [l1, l2]                   # lowers order preserved
    assert ":".join(str(p) for p in res) == "/up:/l1:/l2:/base"
    assert len(res) == 4                          # noqa: PLR2004
    empty = _handler_lowers(up, [], base)
    assert empty == [up, base]
    assert ":".join(str(p) for p in empty) == "/up:/base"
