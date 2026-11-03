"""Tier1: a wiki page renders as safe HTML -- any link but the ones running code, YouTube embedded."""
import pytest

from hashpass.registry.wiki_render import render_page, snippet


@pytest.mark.tier1
def test_links_that_run_code_are_cut_and_raw_html_stays_text() -> None:
    html, _tags, _title = render_page(
        "[x](javascript:alert(1)) [y](vbscript:msgbox) ![](data:text/html,<b>) <script>alert(1)</script>\n")
    assert 'href="javascript' not in html and 'href="vbscript' not in html and 'src="data:text' not in html
    assert "<script>" not in html and "&lt;script&gt;" in html


@pytest.mark.tier1
def test_any_other_link_is_kept() -> None:
    html = render_page("[курс](/c/bob/linux) [хабр](https://habr.com/ru/) [почта](mailto:a@b.c) "
                       "[соседняя](wiki/groups.md)\n")[0]
    for href in ("/c/bob/linux", "https://habr.com/ru/", "mailto:a@b.c", "wiki/groups.md"):
        assert f'href="{href}"' in html


@pytest.mark.tier1
@pytest.mark.parametrize("url", ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ?t=42",
                                 "<https://youtube.com/watch?v=dQw4w9WgXcQ&list=x>"])
def test_a_youtube_link_on_its_own_line_is_embedded(url: str) -> None:
    html = render_page(f"Смотри:\n\n{url}\n")[0]
    assert '<iframe src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ' in html


@pytest.mark.tier1
def test_a_youtube_link_inside_a_sentence_stays_a_link() -> None:
    html = render_page("Вот [видео](https://youtu.be/dQw4w9WgXcQ) про grep.\n")[0]
    assert "<iframe" not in html and 'href="https://youtu.be/dQw4w9WgXcQ"' in html


@pytest.mark.tier1
def test_tables_strikethrough_tags_and_title() -> None:
    html, tags, title = render_page("---\ntags: regex, grep\n---\n# Регулярки\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n~~старое~~\n")
    assert "<table>" in html and "<s>старое</s>" in html and "tags:" not in html
    assert tags == ["regex", "grep"] and title == "Регулярки"


@pytest.mark.tier1
def test_snippet_shows_text_around_the_match_without_markup() -> None:
    text = "# Тема\n\n" + "слово " * 60 + "**квантификатор** `+` значит «один или больше». " + "хвост " * 60
    s = snippet(text, "квантиф")
    assert "квантификатор" in s and "**" not in s and len(s) <= 200  # noqa: PLR2004
    assert snippet("# A\n\nпросто начало текста", "нет такого").startswith("просто начало")
