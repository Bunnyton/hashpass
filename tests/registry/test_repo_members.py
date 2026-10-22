"""Tier1: people in an image -- member / author / maintainer / owner (spec 2026-10-23 §2)."""
import pytest

from hashpass.registry.revisions import RepoIndex
from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page


@pytest.fixture
def lab(registry, tmp_path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/lab", "1", image="one", task="t1")
    assert p.call("PUT", "/revisions/bob/lab", "bob", {"visibility": "private"})[0] == 200  # noqa: PLR2004
    return p


def _role(p: _Courses, who: str, login: str, role: str | None) -> int:
    if role is None:
        return p.call("DELETE", f"/repo-members/bob/lab/{login}", who)[0]
    return p.call("PUT", f"/repo-members/bob/lab/{login}", who, {"role": role})[0]


@pytest.mark.tier1
def test_only_the_owner_sets_roles_and_everyone_who_sees_it_sees_them(lab: _Courses) -> None:
    assert _role(lab, "eve", "kid", "member") == 404  # noqa: PLR2004       # a private image stays unseen
    assert _role(lab, "bob", "kid", "member") == 200  # noqa: PLR2004
    assert _role(lab, "bob", "eve", "author") == 200  # noqa: PLR2004
    assert _role(lab, "bob", "ghost", "author") == 404  # noqa: PLR2004       # no such user
    assert _role(lab, "bob", "kid", "boss") == 400  # noqa: PLR2004
    members = lab.call("GET", "/revisions/bob/lab", "kid")[1]["members"]
    assert members == {"kid": "member", "eve": "author"}


@pytest.mark.tier1
def test_a_member_sees_a_private_image_an_outsider_does_not(lab: _Courses) -> None:
    assert lab.call("GET", "/revisions/bob/lab", "kid")[0] == 404  # noqa: PLR2004
    _role(lab, "bob", "kid", "member")
    assert lab.call("GET", "/revisions/bob/lab", "kid")[0] == 200  # noqa: PLR2004
    assert lab.begin("bob/lab", "1", "kid")[0] == 403  # noqa: PLR2004        # a member does not publish


@pytest.mark.tier1
def test_an_author_publishes_a_maintainer_tags_only_the_owner_changes_settings(lab: _Courses) -> None:
    _role(lab, "bob", "eve", "author")
    _role(lab, "bob", "max", "maintainer")
    assert lab.push("bob/lab", "1", image="two", task="t2", user="eve")[0] == 201  # noqa: PLR2004
    assert RepoIndex(lab.r.store.root / ".repos", "bob/lab").latest("1").by == "eve"
    assert lab.call("POST", "/revisions/bob/lab/1_v2/tag", "eve", {"from": "bob/lab:1_v2", "to": "stable"})[0] == 403  # noqa: PLR2004
    assert lab.call("POST", "/revisions/bob/lab/1_v2/tag", "max", {"from": "bob/lab:1_v2", "to": "stable"})[0] == 201  # noqa: PLR2004
    assert lab.call("PUT", "/revisions/bob/lab", "max", {"visibility": "public"})[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_a_contributor_sees_the_image_on_their_page_and_the_card_lists_people(lab: _Courses) -> None:
    _role(lab, "bob", "eve", "author")
    page = _page(_browser(lab, "eve"), f"{lab.url}/u/eve")[1]
    assert "bob/lab" in page.split("id='tasks'", 1)[1] and "автор" in page
    card = _page(_browser(lab, "eve"), f"{lab.url}/web/image/bob/lab:1")[1]
    assert "id='people'" in card and "/u/eve" in card and "/u/bob" in card


@pytest.mark.tier1
def test_a_member_pulls_a_private_image(lab: _Courses) -> None:
    assert lab.call("GET", "/closure/bob/lab/1?revisions=1", "kid")[0] == 404  # noqa: PLR2004
    _role(lab, "bob", "kid", "member")
    code, body = lab.call("GET", "/closure/bob/lab/1?revisions=1", "kid")
    assert code == 200 and body["refs"][-1] == "bob/lab:1_v1"  # noqa: PLR2004
