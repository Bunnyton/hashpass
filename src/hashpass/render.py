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
_NORMAL_PAUSE = 0.18
_DRAMATIC_PAUSE = 0.55
_DRAMATIC_SLOW = 3.0
_MIN_SPEED = 1
_PAGER_LINES = 40


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
        """Emit `text` through the sink; `instant` writes it whole, else type it char-by-char."""
        mode = mode or self._settings.type_mode
        if mode not in _MODES:
            msg = f"unknown type-mode: {mode!r}"
            raise ValueError(msg)
        if mode == _INSTANT:
            self._sink(text)
            return
        speed = max(self._settings.type_speed, _MIN_SPEED)
        slow = _DRAMATIC_SLOW if mode == _DRAMATIC else 1.0
        char_delay = slow / speed
        punct_pause = _DRAMATIC_PAUSE if mode == _DRAMATIC else _NORMAL_PAUSE
        for ch in text:
            self._sink(ch)
            self._sleep(char_delay)
            if ch in _PUNCT:
                self._sleep(punct_pause)

    def show_file(self, path: Path, *, mode: str | None = None) -> str:
        """Render a file's contents; a large file with `pager on` is emitted whole (paged), not typed."""
        text = Path(path).read_text(encoding="utf-8")
        if self._settings.pager and text.count("\n") + 1 > _PAGER_LINES:
            self._sink(text)
            return text
        self.render(text, mode=mode)
        return text
