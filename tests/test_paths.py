"""Tier1: paths in a command's output are made absolute -- the same files read the same."""
import pytest

from hashpass.paths import absolutize

HOME = "/home/student"
FS = {"/home/student", "/home/student/search", "/home/student/search/a", "/home/student/search/a/f.txt",
      "/home/student/legacy", "/home/student/legacy/notes.txt", "/home/student/.bashrc"}


def _abs(text: str, cwd: str) -> str:
    return absolutize(text, cwd=cwd, exists=FS.__contains__, home=HOME)


@pytest.mark.tier1
@pytest.mark.parametrize(("cwd", "line"), [
    ("/home/student", "search/a/f.txt"),
    ("/home/student", "./search/a/f.txt"),
    ("/home/student", "/home/student/search/a/f.txt"),
    ("/home/student", "~/search/a/f.txt"),
    ("/home/student/search", "a/f.txt"),
    ("/home/student/search", "./a/f.txt"),
    ("/home/student/search/a", "f.txt"),
    ("/home/student/search/a", "../a/f.txt"),
    ("/home/student/search/a", "./"),
])
def test_one_file_reads_the_same_wherever_it_was_found_from(cwd: str, line: str) -> None:
    # User (2026-10-13): «нормализация по выводу команды — если выдаёт файловый путь, нормализовать
    # его, в абсолютные пути, для анализа»; «и cd какие-нибудь тоже».
    got = _abs(line, cwd)
    want = "/home/student/search/a" if line == "./" else "/home/student/search/a/f.txt"
    assert got == want


@pytest.mark.tier1
def test_words_that_are_not_paths_stay_as_they_are() -> None:
    assert _abs("ERROR disk full 2026-09-13 TODO: fix", HOME) == "ERROR disk full 2026-09-13 TODO: fix"


@pytest.mark.tier1
def test_grep_r_prefix_and_several_paths_on_a_line() -> None:
    assert _abs("legacy/notes.txt:TODO: retry", HOME) == "/home/student/legacy/notes.txt:TODO: retry"
    assert _abs("search  ./legacy\t.bashrc", HOME) == \
        "/home/student/search  /home/student/legacy\t/home/student/.bashrc"
    assert _abs(".", "/home/student/search") == "/home/student/search"
