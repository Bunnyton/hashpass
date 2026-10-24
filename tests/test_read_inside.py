"""
Tier1: `accept file` reads the student's file the way the student's system does.

User 2026-10-25 (links, latest.log): «можно создать символьную ссылку на файл, это тоже будет
считаться». A link written with a path from the root (`/home/student/logs/…`) points into the
student's system, not the host's: it is followed inside that system's root.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashpass.taskrun import TaskSession


def _read(rootfs: Path, path: str) -> str | None:
    return TaskSession._read_file(SimpleNamespace(student=SimpleNamespace(rootfs=str(rootfs))), path)  # noqa: SLF001


@pytest.fixture
def home(tmp_path: Path) -> Path:
    logs = tmp_path / "home" / "student" / "logs"
    logs.mkdir(parents=True)
    (logs / "new.log").write_text("fresh\n", encoding="utf-8")
    (tmp_path / "home" / "student" / "latest.log").symlink_to("logs/app.log")
    return tmp_path


@pytest.mark.tier1
@pytest.mark.parametrize("target", ["new.log", "/home/student/logs/new.log", "../logs/./new.log"])
def test_a_chain_of_links_is_followed_inside_the_students_system(home, target) -> None:
    (home / "home/student/logs/app.log").symlink_to(target)
    assert _read(home, "/home/student/latest.log") == "fresh\n"


@pytest.mark.tier1
def test_a_dangling_or_looping_link_reads_as_missing(home) -> None:
    assert _read(home, "/home/student/latest.log") is None            # logs/app.log is not there
    (home / "home/student/logs/app.log").symlink_to("/home/student/latest.log")
    assert _read(home, "/home/student/latest.log") is None


@pytest.mark.tier1
def test_a_link_cannot_climb_out_of_the_students_root(home, tmp_path) -> None:
    (tmp_path.parent / "host-secret.txt").write_text("host\n", encoding="utf-8")
    (home / "home/student/logs/app.log").symlink_to("../../../../host-secret.txt")
    assert _read(home, "/home/student/latest.log") is None
