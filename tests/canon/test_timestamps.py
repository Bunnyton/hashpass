from datetime import UTC, datetime

import pytest

from hashpass.canon.timestamps import build_stamp

_NOW = datetime(2026, 10, 23, 1, 5, tzinfo=UTC)


@pytest.mark.tier1
@pytest.mark.parametrize("line", [
    "lrwxrwxrwx 1 student student 20 Oct 23 01:05 file_link.txt -> dir/file.txt",   # ls -l
    "-rw-r--r-- 1 root root 0 Oct 22 23:59 late.txt",                               # a day off: UTC vs local
    "Fri Oct 23 01:05:44 MSK 2026",                                                 # date
    "backup-2026-10-23.tar.gz",                                                     # ISO in a name
    "отчёт за 23.10.2026",
    "2026/10/23 01:05 started",
])
def test_build_moment_in_a_reference_is_found(line):
    assert build_stamp(f"header\n{line}\nfooter\n", _NOW) == line


@pytest.mark.tier1
@pytest.mark.parametrize("text", [
    "drwxrwxr-x 3 student student 4096 Oct 14 00:23 dir",    # shipped data: a fixed old date
    "app-2026-10-12.log",
    "walrus-6610",
    "2026",                                                   # a bare year is not a moment
    "Oct 23",                                                 # no clock -- could be anything
    "",
])
def test_fixed_dates_and_plain_text_are_not_the_build_moment(text):
    assert build_stamp(text, _NOW) is None
