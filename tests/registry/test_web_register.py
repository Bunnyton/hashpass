"""Tier1: anyone signs up on the pool's site -- not only with `hashpass register` (Todo 2026-11-03)."""
import json
import urllib.request
from http import HTTPStatus

import pytest

from tests.registry.test_web_flow import _opener, _req

PW = "pw-correct1"


def _form(**kw: str) -> dict:
    return {"user": "kid", "password": PW, "password2": PW, "comment": "", **kw}


@pytest.mark.tier1
def test_the_form_is_reached_from_the_login_page(registry) -> None:
    status, _, body = _req(_opener(), "GET", f"{registry.base_url}/web/login")
    assert status == HTTPStatus.OK and "/web/register" in body
    status, _, body = _req(_opener(), "GET", f"{registry.base_url}/web/register")
    assert status == HTTPStatus.OK and "name='password2'" in body


@pytest.mark.tier1
def test_signing_up_makes_the_account_and_signs_in(registry) -> None:
    status, headers, _ = _req(_opener(), "POST", f"{registry.base_url}/web/register",
                              data=_form(comment="ИУ7-31 Иван"))
    assert status == HTTPStatus.SEE_OTHER and headers["Location"] == "/u/kid"
    assert headers["Set-Cookie"].startswith("hp_session=")
    assert registry.users.verify("kid", PW)
    assert registry.users.get("kid")["comment"] == "ИУ7-31 Иван"


@pytest.mark.tier1
@pytest.mark.parametrize(("form", "said"), [
    (_form(password2="другой-пароль1"), "не совпадают"),
    (_form(user="a b"), "латиницей"),
    (_form(password="1", password2="1"), "должен быть не короче"),  # noqa: S106
])
def test_a_bad_form_says_why_and_keeps_the_login(registry, form: dict, said: str) -> None:
    status, _, body = _req(_opener(), "POST", f"{registry.base_url}/web/register", data=form)
    assert status == HTTPStatus.BAD_REQUEST and said in body
    assert not registry.users.has("kid")


@pytest.mark.tier1
def test_a_taken_login_is_refused(registry) -> None:
    registry.users.add("kid", "other-pw-1", group="")
    status, _, body = _req(_opener(), "POST", f"{registry.base_url}/web/register", data=_form())
    assert status == HTTPStatus.CONFLICT and "занят" in body
    assert registry.users.verify("kid", "other-pw-1")


@pytest.mark.tier1
def test_a_filled_trap_field_makes_no_account(registry) -> None:
    status, _, _ = _req(_opener(), "POST", f"{registry.base_url}/web/register", data=_form(website="http://spam"))
    assert status == HTTPStatus.BAD_REQUEST and not registry.users.has("kid")


@pytest.mark.tier1
def test_closed_registration_hides_the_form(registry) -> None:
    registry.users.add("root", PW, role="admin", group="")
    req = urllib.request.Request(f"{registry.base_url}/login", method="POST",  # noqa: S310
                                 data=json.dumps({"user": "root", "password": PW}).encode(),
                                 headers={"Content-Type": "application/json"})
    token = json.loads(_opener().open(req, timeout=10).read())["token"]
    req = urllib.request.Request(f"{registry.base_url}/admin/registration", method="POST",  # noqa: S310
                                 data=json.dumps({"open": False}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    _opener().open(req, timeout=10)
    assert "/web/register" not in _req(_opener(), "GET", f"{registry.base_url}/web/login")[2]
    status, _, body = _req(_opener(), "POST", f"{registry.base_url}/web/register", data=_form())
    assert status == HTTPStatus.FORBIDDEN and "закрыта" in body and not registry.users.has("kid")
