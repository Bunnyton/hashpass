"""Typewriter render layer (§7.2): paced system replies + instant command output; injectable."""
import sys
import time
from collections.abc import Callable
from pathlib import Path

from hashpass.recipe.model import Settings

_INSTANT = "instant"
_DRAMATIC = "dramatic"
_MODES = ("instant", "normal", "dramatic")
_PUNCT = frozenset(".,!?;:…—")
_SENTENCE_END = frozenset(".!?…")
# Typing is ALWAYS character-by-character (a real typewriter). The earlier "jerky" feel came NOT
# from per-char typing but from a big fixed pause after every punctuation mark (a stutter at each
# comma). So keep an even per-char delay and add only a small, PROPORTIONAL breath at sentence
# ends / line breaks -- no stall at commas.
_SENTENCE_MULT = 4       # sentence-end / newline breath = this many extra char-delays
_DRAMATIC_PAUSE = 0.55
_DRAMATIC_SLOW = 3.0
_MIN_SPEED = 1
_PAGER_LINES = 40
_PAGER_BYTES = 4000  # a large single-line file is paged too, not just many-line files


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
        Emit `text` one character at a time at a paced speed (or whole, for `instant`).

        A real typewriter: even per-character delay, plus a small proportional breath at sentence
        ends / line breaks (no stall at commas -- that fixed per-punctuation pause was the "jerky"
        feel). `dramatic` slows the whole thing and holds a long beat at every punctuation mark.
        """
        mode = mode or self._settings.type_mode
        if mode not in _MODES:
            msg = f"unknown type-mode: {mode!r}"
            raise ValueError(msg)
        if mode == _INSTANT:
            self._sink(text)
            return
        speed = max(self._settings.type_speed, _MIN_SPEED)
        dramatic = mode == _DRAMATIC
        char_delay = (_DRAMATIC_SLOW if dramatic else 1.0) / speed
        for ch in text:
            self._sink(ch)
            self._sleep(char_delay)
            if dramatic:
                if ch in _PUNCT:
                    self._sleep(_DRAMATIC_PAUSE)
            elif ch in _SENTENCE_END or ch == "\n":
                self._sleep(char_delay * _SENTENCE_MULT)   # a small, even breath -- never a stutter

    def show_file(self, path: Path, *, mode: str | None = None) -> str:
        """Render a file's contents; a large file with `pager on` is emitted whole (paged), not typed."""
        text = Path(path).read_text(encoding="utf-8")
        too_big = text.count("\n") + 1 > _PAGER_LINES or len(text) > _PAGER_BYTES
        if self._settings.pager and too_big:
            self._sink(text)
            return text
        self.render(text, mode=mode)
        return text
