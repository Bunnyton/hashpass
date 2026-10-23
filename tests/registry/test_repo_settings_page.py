"""
Tier1: an image's settings live on a page of their own, like GitHub's Settings tab.

User 2026-10-23: «Настройки со страницы все еще убери. Сначала участники (назови как-то по
другому) … Потом уже используется в курсах. А настройки отдельно».
"""
import pytest

from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_repo_members import _role, lab  # noqa: F401  (the fixture)


@pytest.mark.tier1
def test_the_image_page_lists_collaborators_then_courses_and_keeps_no_settings(lab: _Courses) -> None:  # noqa: F811
    _role(lab, "bob", "eve", "author")
    card = _page(_browser(lab, "bob"), f"{lab.url}/web/image/bob/lab:1")[1]
    side = card.split("class='repo-side'", 1)[1]
    assert "Соавторы" in side and "Участники" not in side
    assert side.index("id='people'") < side.index("id='courses'")
    assert "id='settings'" not in card and "name='visibility'" not in card and "/repo-members/" not in card
    assert "href='/web/settings/bob/lab'" in card


@pytest.mark.tier1
def test_the_owner_changes_visibility_tags_and_roles_on_the_settings_page(lab: _Courses) -> None:  # noqa: F811
    _role(lab, "bob", "eve", "author")
    code, page = _page(_browser(lab, "bob"), f"{lab.url}/web/settings/bob/lab")
    assert code == 200  # noqa: PLR2004
    assert "name='visibility'" in page and "name='hide_sources'" in page
    assert "data-api='PUT /repo-members/bob/lab/eve'" in page and "Соавторы" in page
    assert "/revisions/bob/lab/1_v1/tag" in page


@pytest.mark.tier1
def test_only_the_owner_opens_the_settings_page(lab: _Courses) -> None:  # noqa: F811
    _role(lab, "bob", "eve", "author")
    card = _page(_browser(lab, "eve"), f"{lab.url}/web/image/bob/lab:1")[1]
    assert "/web/settings/" not in card
    code, page = _page(_browser(lab, "eve"), f"{lab.url}/web/settings/bob/lab")
    assert code == 404 or "name='visibility'" not in page  # noqa: PLR2004
