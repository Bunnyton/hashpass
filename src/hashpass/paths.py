"""
Make file paths in a command's output absolute, so the same files read the same for a check.

`find .` from ~/search, `find search` from ~, `find ~/search` and `find /home/student/search` print
different text for the same files; so do `grep -r` prefixes (`legacy/notes.txt:…`). A check that
compares OUTPUT should compare the files, not the spelling (user, 2026-10-13: «нормализация по
выводу команды — если выдаёт файловый путь, нормализовать его в абсолютные пути»).

A word is a path only if, resolved against the command's working directory (and `~`), it exists
in the student's system -- so ERROR, TODO, dates and other words stay untouched.
"""
import posixpath
import re
from collections.abc import Callable

_WORD = re.compile(r"\S+")


def _resolve(word: str, cwd: str, home: str) -> str:
    if word == "~" or word.startswith("~/"):
        word = home + word[1:]
    elif not word.startswith("/"):
        word = posixpath.join(cwd, word)
    return posixpath.normpath(word)


def absolutize(text: str, *, cwd: str, exists: Callable[[str], bool],
               home: str = "/home/student") -> str:
    """Return `text` with every word that names an existing path rewritten as its absolute path."""
    cwd = cwd or home

    def one(m: re.Match[str]) -> str:
        word = m.group(0)
        path = _resolve(word.rstrip("/") or "/", cwd, home)
        if exists(path):
            return path
        head, sep, tail = word.partition(":")      # grep -r / grep -n: `path:rest`
        if sep and head:
            path = _resolve(head.rstrip("/") or "/", cwd, home)
            if exists(path):
                return f"{path}:{tail}"
        return word

    return _WORD.sub(one, text)
