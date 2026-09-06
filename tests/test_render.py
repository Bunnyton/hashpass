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
def test_normal_flow_streams_words_with_a_clamped_even_beat():
    # Default `word` flow: each word carries its trailing space as ONE write (one beat per word),
    # and the beat is clamped to a tight band -> even, fast rhythm, never length-scaled.
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="normal", type_speed=50), sink=chunks.append, sleep=sleeps.append)
    r.render("Hi there.")
    assert chunks == ["Hi ", "there."]
    assert "".join(chunks) == "Hi there."
    # both words exceed the clamp ceiling (0.055); sentence end '.' adds a small breath (0.11).
    assert sleeps == [0.055, 0.055, 0.11]


@pytest.mark.tier1
def test_word_flow_clamps_short_and_long_and_beats_at_comma():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_speed=50), sink=chunks.append, sleep=sleeps.append)
    r.render("a, b")
    assert chunks == ["a, ", "b"]
    # "a, " (3 chars * .02 = .06 -> clamped to .055), comma beat .045, then "b" (1 char -> floor .02)
    assert sleeps == [0.055, 0.045, 0.02]


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
