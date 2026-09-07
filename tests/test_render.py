"""Validate the typewriter render layer with injected sink + sleep (no real sleeping)."""
import pytest

from hashpass.recipe.model import Settings
from hashpass.render import Renderer


def _cap() -> tuple[list[str], list[float]]:
    chunks: list[str] = []
    sleeps: list[float] = []
    return chunks, sleeps


@pytest.mark.tier1
def test_instant_never_sleeps_single_write():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=sleeps.append)
    r.render("a long command output\nwith lines")
    assert chunks == ["a long command output\nwith lines"]
    assert sleeps == []


@pytest.mark.tier1
def test_normal_types_char_by_char_with_even_delay():
    # Typing is ALWAYS one character at a time, with an even per-char delay -- no per-punctuation
    # stall (the old stutter). Only a sentence end / newline gets a small proportional breath.
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="normal", type_speed=50), sink=chunks.append, sleep=sleeps.append)
    r.render("ab")
    assert chunks == ["a", "b"]                       # one char per write
    assert sleeps == [1 / 50, 1 / 50]                 # even delay, nothing extra


@pytest.mark.tier1
def test_no_stutter_at_comma_but_breath_at_sentence_end():
    cd = 1 / 50
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_speed=50), sink=chunks.append, sleep=sleeps.append)
    r.render("a, b.")
    assert chunks == ["a", ",", " ", "b", "."]
    # comma adds NOTHING (no stall); only the sentence-ending '.' adds a small breath (4x char delay)
    assert sleeps == [cd, cd, cd, cd, cd, cd * 4]


@pytest.mark.tier1
def test_dramatic_pauses_at_punctuation():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_speed=45), sink=chunks.append, sleep=sleeps.append)
    r.render("Hi!", mode="dramatic")
    char_delay = 3.0 / 45                              # dramatic slows the whole thing 3x
    assert chunks == ["H", "i", "!"]                   # still char-by-char
    assert sleeps == [char_delay, char_delay, char_delay, 0.55]  # long beat after '!'


@pytest.mark.tier1
def test_show_file_small_typed_large_paged(tmp_path):
    small = tmp_path / "s.txt"
    small.write_text("one\ntwo\n", encoding="utf-8")
    big = tmp_path / "b.txt"
    big.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="normal", pager=True), sink=chunks.append, sleep=sleeps.append)
    assert r.show_file(small).startswith("one")
    assert len(chunks) > 1          # small file typed char-by-char
    chunks2, sleeps2 = _cap()
    r2 = Renderer(Settings(pager=True), sink=chunks2.append, sleep=sleeps2.append)
    r2.show_file(big)
    assert len(chunks2) == 1        # large + pager -> emitted whole
    assert sleeps2 == []


@pytest.mark.tier1
def test_unknown_mode_raises():
    r = Renderer(Settings(), sink=lambda _s: None, sleep=lambda _s: None)
    with pytest.raises(ValueError, match="unknown type-mode"):
        r.render("x", mode="turbo")


@pytest.mark.tier1
def test_show_file_large_single_line_paged(tmp_path):
    f = tmp_path / "wide.txt"
    f.write_text("Z" * 5000, encoding="utf-8")  # one line but > _PAGER_BYTES
    chunks, sleeps = _cap()
    r = Renderer(Settings(pager=True), sink=chunks.append, sleep=sleeps.append)
    r.show_file(f)
    assert chunks == ["Z" * 5000]  # paged whole, never typed
    assert sleeps == []
