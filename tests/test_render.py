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
def test_normal_flow_emits_whole_words_paced_by_length():
    # Default `word` flow: each word is ONE sink write, paced by its length -> no per-char stutter.
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="normal", type_speed=50), sink=chunks.append, sleep=sleeps.append)
    r.render("Hi there.")
    assert chunks == ["Hi", " ", "there."]
    assert "".join(chunks) == "Hi there."
    # "Hi"->2 chars, " "->1, "there."->6; sentence end '.' adds a fuller breath (2x normal pause).
    assert sleeps == [2 / 50, 1 / 50, 6 / 50, 0.13 * 2]


@pytest.mark.tier1
def test_word_flow_short_beat_at_comma():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_speed=50), sink=chunks.append, sleep=sleeps.append)
    r.render("a, b")
    assert chunks == ["a,", " ", "b"]
    assert sleeps == [2 / 50, 0.13, 1 / 50, 1 / 50]   # comma -> single (short) beat


@pytest.mark.tier1
def test_char_flow_is_opt_in_classic_typewriter():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="normal", type_flow="char", type_speed=50),
                 sink=chunks.append, sleep=sleeps.append)
    r.render("ab")
    assert chunks == ["a", "b"]
    assert sleeps == [1 / 50, 1 / 50]


@pytest.mark.tier1
def test_dramatic_pauses_at_punctuation():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_speed=45), sink=chunks.append, sleep=sleeps.append)
    r.render("Hi!", mode="dramatic")
    char_delay = 3.0 / 45
    assert chunks == ["Hi!"]                       # one word, emitted whole
    assert sleeps == [3 * char_delay, 0.55]        # paced by length, then the dramatic pause after '!'


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
