"""Tier2: pool pages ask for a permission box, not a role (spec 2026-10-25 §2, plan task 4)."""
import json
import urllib.parse
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry
from tests.registry.test_images_web import _opener, _req, _seed
from tests.registry.test_push_commit import _http

_PW = "pass123!"


def _cookie(registry, user: str) -> tuple:
    opener = _opener()
    _, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login", data={"user": user, "password": _PW})
    return opener, headers["Set-Cookie"].split(";")[0]


def _admin(registry, user: str, boxes: list[str]) -> tuple:
    """Make an admin `user` with `boxes` -- not the pool's owner (`admin` is, made first)."""
    if not registry.users.has("admin"):
        registry.users.add("admin", _PW, role="admin")
    registry.users.add(user, _PW, role="admin")
    registry.users.set_perms(user, boxes)
    return _cookie(registry, user)


def _status(registry, opener, cookie, path: str) -> int:
    return _req(opener, "GET", f"{registry.base_url}{path}", cookie=cookie)[0]


@pytest.mark.tier2
def test_a_former_author_keeps_its_own_images(registry, tmp_path) -> None:
    registry.users.add("alice", _PW)
    path = registry.users._path                                     # noqa: SLF001
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["alice"]["role"] = "author"                                  # as stored on the pool before
    path.write_text(json.dumps(raw), encoding="utf-8")
    _seed(registry, "alice/lab:1", tmp_path, task=True)
    _seed(registry, "bob/lab:1", tmp_path, task=True)
    opener, cookie = _cookie(registry, "alice")
    assert _status(registry, opener, cookie, f"/web/image/{urllib.parse.quote('alice/lab:1')}") == HTTPStatus.OK
    code, rows = _http("GET", f"{registry.base_url}/images", token=RemoteRegistry(registry.base_url).login("alice", _PW))
    assert code == HTTPStatus.OK and "alice/lab:1" in {r["ref"] for r in rows["images"]}   # its own task, in full
    code, _, _ = _req(opener, "POST", f"{registry.base_url}/web/catalog/add", cookie=cookie,
                      data={"ref": "alice/lab:1"})
    assert code != HTTPStatus.OK                                     # the pool's catalog: `content`


@pytest.mark.tier2
@pytest.mark.parametrize(("box", "path"), [("people", "/web/users"), ("progress", "/web/user/admin")])
def test_a_page_needs_its_box(registry, box: str, path: str) -> None:
    others = [k for k in ("admins", "content", "people", "progress") if k != box]
    opener, cookie = _admin(registry, "without", others)
    assert _status(registry, opener, cookie, path) != HTTPStatus.OK
    opener, cookie = _admin(registry, "with", [box])
    assert _status(registry, opener, cookie, path) == HTTPStatus.OK


@pytest.mark.tier2
def test_making_an_admin_needs_the_admins_box(registry) -> None:
    _admin(registry, "plain", ["content", "people", "progress"])
    registry.users.add("kid", _PW)
    client = RemoteRegistry(registry.base_url)
    tok = client.login("plain", _PW)
    with pytest.raises(Exception, match="403"):
        client.set_role("kid", "admin", token=tok)
    _admin(registry, "keeper", ["admins", "content"])
    client.set_role("kid", "admin", token=client.login("keeper", _PW))
    assert registry.users.role("kid") == "admin"


@pytest.mark.tier2
def test_the_pool_settings_need_the_content_box(registry) -> None:
    _admin(registry, "people_only", ["people"])
    _admin(registry, "editor", ["content"])
    client = RemoteRegistry(registry.base_url)
    url = f"{registry.base_url}/pool/settings"
    assert _http("PUT", url, token=client.login("people_only", _PW), body={"auto_approve": True})[0] == HTTPStatus.FORBIDDEN
    assert _http("PUT", url, token=client.login("editor", _PW), body={"auto_approve": True})[0] == HTTPStatus.OK
