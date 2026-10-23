"""Tier1: a push into someone else's image is a proposal (spec 2026-10-23 §3)."""
import pytest

from hashpass.registry.revisions import RepoIndex
from tests.registry.test_course_api import _Courses


@pytest.fixture
def lab(registry, tmp_path) -> _Courses:
    p = _Courses(registry, tmp_path)
    p.push("bob/lab", "1", image="one", task="t1")
    return p


def _propose(p: _Courses, user: str, message: str) -> tuple[int, dict]:
    code, body = p.call("POST", "/revisions/bob/lab/1", user, {"propose": True})
    assert code == 201, body  # noqa: PLR2004
    name, sid = body["name"], body["staging"]
    assert p.put("image", name, "1", sid, p.blob(name, "1", "better"), user) == 201  # noqa: PLR2004
    assert p.put("task", name, "1", sid, p.task("t-better"), user) == 201  # noqa: PLR2004
    return p.call("POST", f"/revisions/{name}/1/commit", user, {"staging": sid, "message": message})


@pytest.mark.tier1
def test_an_old_client_without_rights_is_still_refused(lab: _Courses) -> None:
    assert lab.begin("bob/lab", "1", "kid")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_a_push_without_rights_lands_in_a_fork_and_opens_a_proposal(lab: _Courses) -> None:
    code, body = _propose(lab, "kid", "опечатка в брифе")
    assert code == 201 and body["proposal"]["to"] == "bob/lab"  # noqa: PLR2004
    assert RepoIndex(lab.r.store.root / ".repos", "kid/lab").fork_of.startswith("bob/lab:")
    merges = lab.call("GET", "/revisions/bob/lab/merges", "bob")[1]["merges"]
    assert [(m["by"], m["comment"], m["state"]) for m in merges] == [("kid", "опечатка в брифе", "open")]


@pytest.mark.tier1
def test_accepting_makes_a_version_whose_author_is_who_proposed(lab: _Courses) -> None:
    _propose(lab, "kid", "опечатка в брифе")
    mid = lab.call("GET", "/revisions/bob/lab/merges", "bob")[1]["merges"][0]["id"]
    assert lab.call("POST", f"/revisions/bob/lab/merges/{mid}", "bob", {"action": "merge"})[0] == 200  # noqa: PLR2004
    rev = RepoIndex(lab.r.store.root / ".repos", "bob/lab").latest("1")
    assert (rev.n, rev.by, rev.accepted_by, rev.message) == (2, "kid", "bob", "опечатка в брифе")


@pytest.mark.tier1
def test_two_versions_compare_like_github(lab: _Courses) -> None:
    from tests.registry.test_course_web import _browser, _page  # noqa: PLC0415
    lab.push("bob/lab", "1", image="two", task="t2")
    status, html = _page(_browser(lab, "bob"), f"{lab.url}/web/compare/bob/lab?from=1_v1&to=1_v2")
    assert status == 200 and "Сравнение версий" in html  # noqa: PLR2004
    versions = _page(_browser(lab, "bob"), f"{lab.url}/web/versions/bob/lab")[1]   # the commit list
    assert "/web/compare/bob/lab?from=1_v1&to=1_v2" in versions
