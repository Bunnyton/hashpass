"""Typewriter render layer (§7.2): paced system replies + instant command output; injectable."""
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

from hashpass.recipe.model import Settings

_INSTANT = "instant"
_DRAMATIC = "dramatic"
_CHAR = "char"
_MODES = ("instant", "normal", "dramatic")
_PUNCT = frozenset(".,!?;:…—")
_SENTENCE_END = frozenset(".!?…")
_NORMAL_PAUSE = 0.13
_DRAMATIC_PAUSE = 0.55
_DRAMATIC_SLOW = 3.0
_MIN_SPEED = 1
_PAGER_LINES = 40
_PAGER_BYTES = 4000  # a large single-line file is paged too, not just many-line files
_TOKEN_RE = re.compile(r"\S+|\s+")   # a "word" (visible run) or a whitespace run


def _stdout_write(text: str) -> None:
    """Default sink: write to stdout without an added newline."""
    sys.stdout.write(text)


class Renderer:
    """Render text through an injected sink at a paced (or instant) speed (§7.2)."""

    def __init__(self, settings: Settings, *,
                 sink: Callable[[str], None] = _stdout_write,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        """Bind render settings plus injectable `sink` (emit) and `sleep` (pacing) callables."""
        self._settings = settings
        self._sink = sink
        self._sleep = sleep

    def render(self, text: str, *, mode: str | None = None) -> None:
        """
        Emit `text` through the sink at a paced speed (or whole, for `instant`).

        Default flow is `word`: whole words are emitted as one write and paced by their length,
        so the cadence varies organically and there is no per-character stutter (the live sink
        writes over a socket, where char-by-char + sub-10ms sleeps read as jerky). `type-flow char`
        keeps the classic one-character-at-a-time typewriter.
        """
        mode = mode or self._settings.type_mode
        if mode not in _MODES:
            msg = f"unknown type-mode: {mode!r}"
            raise ValueError(msg)
        if mode == _INSTANT:
            self._sink(text)
            return
        speed = max(self._settings.type_speed, _MIN_SPEED)
        char_delay = (_DRAMATIC_SLOW if mode == _DRAMATIC else 1.0) / speed
        dramatic = mode == _DRAMATIC
        if self._settings.type_flow == _CHAR:
            self._type_chars(text, char_delay, dramatic=dramatic)
        else:
            self._type_words(text, char_delay, dramatic=dramatic)

    def _pause_after(self, chunk: str, *, dramatic: bool) -> None:
        """Sleep a breathing pause after a chunk whose last visible char is punctuation (or a newline)."""
        stripped = chunk.rstrip()
        end = stripped[-1] if stripped else ""
        if dramatic:
            if end in _PUNCT:
                self._sleep(_DRAMATIC_PAUSE)
            return
        if end in _SENTENCE_END or "\n" in chunk:
            self._sleep(_NORMAL_PAUSE * 2)      # a fuller breath between sentences / lines
        elif end in _PUNCT:
            self._sleep(_NORMAL_PAUSE)          # a shorter beat at a comma / colon

    def _type_chars(self, text: str, char_delay: float, *, dramatic: bool) -> None:
        """Classic typewriter: one character at a time (`type-flow char`)."""
        for ch in text:
            self._sink(ch)
            self._sleep(char_delay)
            self._pause_after(ch, dramatic=dramatic)

    def _type_words(self, text: str, char_delay: float, *, dramatic: bool) -> None:
        """Smooth default: emit each word (and whitespace run) whole, paced by its length."""
        for token in _TOKEN_RE.findall(text):
            self._sink(token)
            self._sleep(char_delay * len(token))
            self._pause_after(token, dramatic=dramatic)

    def show_file(self, path: Path, *, mode: str | None = None) -> str:
        """Render a file's contents; a large file with `pager on` is emitted whole (paged), not typed."""
        text = Path(path).read_text(encoding="utf-8")
        too_big = text.count("\n") + 1 > _PAGER_LINES or len(text) > _PAGER_BYTES
        if self._settings.pager and too_big:
            self._sink(text)
            return text
        self.render(text, mode=mode)
        return text
