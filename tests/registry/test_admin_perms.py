"""Tier2: making admins and setting their boxes on the pool (spec 2026-10-25 §1-§2, plan task 5)."""
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry
from tests.registry.test_images_web import _req
from tests.registry.test_pool_perms_gates import _PW, _admin, _cookie
from tests.registry.test_push_commit import _http


def _put_perms(registry, actor: str, user: str, boxes: list[str]) -> int:
    tok = RemoteRegistry(registry.base_url).login(actor, _PW)
    return _http("PUT", f"{registry.base_url}/admin/perms", token=tok, body={"user": user, "perms": boxes})[0]


@pytest.mark.tier2
def test_admins_box_needed_to_make_an_admin(registry) -> None:
    _admin(registry, "plain", ["content", "people", "progress"])
    _admin(registry, "keeper", ["admins", "people"])
    registry.users.add("kid", _PW)
    assert _put_perms(registry, "plain", "keeper", ["people"]) == HTTPStatus.FORBIDDEN
    opener, cookie = _cookie(registry, "keeper")
    _req(opener, "POST", f"{registry.base_url}/web/users/role", cookie=cookie, data={"user": "kid", "role": "admin"})
    assert registry.users.role("kid") == "admin"
    assert registry.users.get("kid")["perms"] == ["people"]       # the default, cut to what keeper holds


@pytest.mark.tier2
def test_a_box_one_lacks_cannot_be_given(registry) -> None:
    _admin(registry, "keeper", ["admins", "people"])
    _admin(registry, "other", ["content"])
    assert _put_perms(registry, "keeper", "other", ["content", "progress"]) == HTTPStatus.FORBIDDEN
    assert _put_perms(registry, "keeper", "other", ["content", "people"]) == HTTPStatus.OK
    assert registry.users.get("other")["perms"] == ["content", "people"]   # content kept: not keeper's to take
    assert _put_perms(registry, "keeper", "other", []) == HTTPStatus.OK
    assert registry.users.get("other")["perms"] == ["content"]


@pytest.mark.tier2
def test_nobody_touches_the_owner(registry) -> None:
    _admin(registry, "keeper", ["admins", "content", "people", "progress"])
    assert _put_perms(registry, "keeper", "admin", []) == HTTPStatus.FORBIDDEN
    opener, cookie = _cookie(registry, "keeper")
    _req(opener, "POST", f"{registry.base_url}/web/users/role", cookie=cookie, data={"user": "admin", "role": "user"})
    assert registry.users.role("admin") == "admin"


@pytest.mark.tier2
def test_nobody_changes_own_perms(registry) -> None:
    _admin(registry, "keeper", ["admins", "people"])
    assert _put_perms(registry, "keeper", "keeper", ["admins"]) == HTTPStatus.FORBIDDEN


@pytest.mark.tier2
def test_users_page_shows_boxes_to_admins_box_only(registry) -> None:
    _admin(registry, "keeper", ["admins", "people"])
    _admin(registry, "clerk", ["people"])
    registry.users.add("kid", _PW)
    opener, cookie = _cookie(registry, "keeper")
    page = _req(opener, "GET", f"{registry.base_url}/web/users", cookie=cookie)[2]
    assert "name='perms'" in page and "Убрать из админов" in page and "Сделать админом" in page
    assert "владелец" in page                                   # the owner: marked, no buttons
    opener, cookie = _cookie(registry, "clerk")
    page = _req(opener, "GET", f"{registry.base_url}/web/users", cookie=cookie)[2]
    assert "name='perms'" not in page and "Убрать из админов" not in page
