"""Tier1: private repositories and hidden service files (spec 2026-10-21 §2.5, §2.6)."""
import io
import tarfile
from pathlib import Path

import pytest

from tests.registry.test_course_api import _Courses


def _src(readme: bytes, taskfile: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (("README.md", readme), ("Taskfile", taskfile)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Courses:
    p = _Courses(registry, tmp_path)
    sid = p.begin("bob/lab", "1")[1]["staging"]
    p.put("image", "bob/lab", "1", sid, p.blob("bob/lab", "1", "one"))
    p.put("source", "bob/lab", "1", sid, _src(b"# lab", b"solve answer"))
    p.commit("bob/lab", "1", sid)
    return p


@pytest.mark.tier1
def test_sources_open_by_default_and_hidden_on_request(pool: _Courses) -> None:
    assert pool.call("GET", "/source/bob/lab/1?path=Taskfile", "kid")[0] == 200  # noqa: PLR2004
    assert pool.call("PUT", "/revisions/bob/lab", "eve", {"hide_sources": True})[0] == 403  # noqa: PLR2004
    assert pool.call("PUT", "/revisions/bob/lab", "bob", {"hide_sources": True})[0] == 200  # noqa: PLR2004
    assert pool.call("GET", "/source/bob/lab/1?path=Taskfile", "kid")[0] == 403  # noqa: PLR2004
    assert pool.call("GET", "/source/bob/lab/1?path=README.md", "kid")[0] == 200  # noqa: PLR2004
    assert pool.call("GET", "/source/bob/lab/1?path=Taskfile", "bob")[0] == 200  # noqa: PLR2004


@pytest.mark.tier1
def test_a_private_repository_is_invisible_to_others(pool: _Courses) -> None:
    assert pool.call("PUT", "/revisions/bob/lab", "bob", {"visibility": "private"})[0] == 200  # noqa: PLR2004
    assert pool.call("GET", "/revisions/bob/lab", "kid")[0] == 404  # noqa: PLR2004
    rows = pool.call("GET", "/images", "kid")[1]["images"]
    assert not [r for r in rows if r["repo"] == "bob/lab"]
    assert pool.call("GET", "/source/bob/lab/1?path=README.md", "kid")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_private_is_refused_while_a_public_course_holds_it(pool: _Courses) -> None:
    pool.call("POST", "/courses", "bob", {"name": "open"})
    pool.call("POST", "/courses/bob/open/tasks", "bob", {"repo": "bob/lab", "tag": "1"})
    code, body = pool.call("PUT", "/revisions/bob/lab", "bob", {"visibility": "private"})
    assert code == 409 and body["blockers"] == ["bob/open"]  # noqa: PLR2004


@pytest.mark.tier1
def test_a_public_image_cannot_stand_on_a_private_one(pool: _Courses) -> None:
    pool.call("PUT", "/revisions/bob/lab", "bob", {"visibility": "private"})
    code, body = pool.push("bob/child", "1", image="c", parents=("bob/lab:1",))
    assert code == 409 and "приватном" in body["error"]  # noqa: PLR2004
