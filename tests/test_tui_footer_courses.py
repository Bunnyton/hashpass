"""User 2026-11-09: «кнопка курсы отсутствует» -- it was 6th in the footer and fell off 80 columns."""
import pytest

from hashpass.tui import PoolTUI


@pytest.mark.tier1
def test_courses_key_comes_right_after_quit_in_the_footer() -> None:
    shown = [b.action for b in PoolTUI.BINDINGS if b.show]
    assert shown[:2] == ["quit", "courses"]
