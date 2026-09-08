"""Tier2: web login/cookie/dashboard flow over the live server."""
import re
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        return None  # inspect 303s instead of following them


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def _req(opener, method, url, *, cookie=None, data=None) -> tuple:
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
    try:
        resp = opener.open(req, timeout=10)
        return resp.status, resp.headers, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode("utf-8")


@pytest.mark.tier2
def test_login_sets_cookie_and_dashboard_lists_students(registry):
    registry.users.add("teacher", "pw", role="admin", group="")
    registry.users.add("s1", "pw", role="student", group="ИУ7-31", comment="Иван")
    opener = _opener()

    # anonymous dashboard -> redirect to login
    status, headers, _ = _req(opener, "GET", f"{registry.base_url}/web")
    assert status == HTTPStatus.SEE_OTHER
    assert headers["Location"] == "/web/login"

    # login -> 303 + session cookie
    status, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login",
                              data={"user": "teacher", "password": "pw"})
    assert status == HTTPStatus.SEE_OTHER
    cookie = headers["Set-Cookie"].split(";")[0]
    assert cookie.startswith("hp_session=")

    # dashboard with the cookie renders the student
    status, _, body = _req(opener, "GET", f"{registry.base_url}/web", cookie=cookie)
    assert status == HTTPStatus.OK
    assert "Иван" in body


@pytest.mark.tier2
def test_web_login_rejects_student(registry):
    registry.users.add("s1", "pw", role="student", group="G")
    status, _, body = _req(_opener(), "POST", f"{registry.base_url}/web/login",
                           data={"user": "s1", "password": "pw"})
    assert status == HTTPStatus.UNAUTHORIZED
    assert "нет доступа" in body


@pytest.mark.tier2
def test_install_sh_is_public(registry):
    status, _, body = _req(_opener(), "GET", f"{registry.base_url}/install.sh")
    assert status == HTTPStatus.OK
    assert "pip install --user" in body
    assert "pool.json" in body
    assert registry.base_url in body   # templated with this pool's URL


@pytest.mark.tier2
def test_engine_install_requires_author(registry):
    status, headers, _ = _req(_opener(), "GET", f"{registry.base_url}/install-engine.sh")
    assert status == HTTPStatus.SEE_OTHER            # anonymous -> login
    assert headers["Location"] == "/web/login"
    registry.users.add("admin", "pw", role="admin", group="")
    opener = _opener()
    _, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login",
                         data={"user": "admin", "password": "pw"})
    cookie = headers["Set-Cookie"].split(";")[0]
    status, _, body = _req(opener, "GET", f"{registry.base_url}/install-engine.sh", cookie=cookie)
    assert status == HTTPStatus.OK
    assert "engine" in body


@pytest.mark.tier2
def test_web_admin_can_toggle_registration(registry):
    registry.users.add("admin", "pw", role="admin", group="")
    opener = _opener()
    _, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login",
                         data={"user": "admin", "password": "pw"})
    cookie = headers["Set-Cookie"].split(";")[0]
    _req(opener, "POST", f"{registry.base_url}/web/users/registration",
         cookie=cookie, data={"open": "false"})
    _, _, body = _req(opener, "GET", f"{registry.base_url}/web/users", cookie=cookie)
    assert "Открыть регистрацию" in body   # now closed -> the toggle offers to open it


def _admin_cookie(registry) -> tuple:
    registry.users.add("admin", "pw", role="admin", group="")
    opener = _opener()
    _, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login",
                         data={"user": "admin", "password": "pw"})
    return opener, headers["Set-Cookie"].split(";")[0]


@pytest.mark.tier2
def test_change_own_password(registry):
    opener, cookie = _admin_cookie(registry)
    status, _, body = _req(opener, "POST", f"{registry.base_url}/web/password", cookie=cookie,
                           data={"old": "pw", "new": "pw2", "confirm": "pw2"})
    assert status == HTTPStatus.OK
    assert "Пароль изменён" in body
    assert _req(_opener(), "POST", f"{registry.base_url}/web/login",
                data={"user": "admin", "password": "pw"})[0] == HTTPStatus.UNAUTHORIZED
    assert _req(_opener(), "POST", f"{registry.base_url}/web/login",
                data={"user": "admin", "password": "pw2"})[0] == HTTPStatus.SEE_OTHER


@pytest.mark.tier2
def test_admin_reset_link_flow(registry):
    registry.users.add("stud", "old", role="student", group="G")
    opener, cookie = _admin_cookie(registry)
    status, _, body = _req(opener, "POST", f"{registry.base_url}/web/users/reset", cookie=cookie,
                           data={"user": "stud"})
    assert status == HTTPStatus.OK
    token = re.search(r"token=([^<\s]+)", body).group(1)
    reset = _req(_opener(), "POST", f"{registry.base_url}/web/reset",
                 data={"token": token, "new": "newpw", "confirm": "newpw"})
    assert reset[0] == HTTPStatus.SEE_OTHER            # -> back to login
    assert RemoteRegistry(registry.base_url).login("stud", "newpw")   # new password works


@pytest.mark.tier2
def test_inline_role_change(registry):
    registry.users.add("stud", "pw", role="student", group="G")
    opener, cookie = _admin_cookie(registry)
    _req(opener, "POST", f"{registry.base_url}/web/users/role", cookie=cookie,
         data={"user": "stud", "role": "author"})
    assert registry.users.role("stud") == "author"


@pytest.mark.tier2
def test_admin_cannot_change_or_delete_self(registry):
    opener, cookie = _admin_cookie(registry)   # user "admin"
    _req(opener, "POST", f"{registry.base_url}/web/users/role", cookie=cookie,
         data={"user": "admin", "role": "student"})
    assert registry.users.role("admin") == "admin"     # self role change ignored
    _req(opener, "POST", f"{registry.base_url}/web/users/delete", cookie=cookie,
         data={"user": "admin"})
    assert registry.users.has("admin")                 # self delete ignored


@pytest.mark.tier2
def test_delete_user_and_group(registry):
    registry.users.add("s1", "pw", role="student", group="ИУ7-31")
    registry.users.add("s2", "pw", role="student", group="ИУ7-31")
    registry.users.add("s3", "pw", role="student", group="ИУ7-32")
    opener, cookie = _admin_cookie(registry)
    _req(opener, "POST", f"{registry.base_url}/web/users/delete", cookie=cookie, data={"user": "s3"})
    assert not registry.users.has("s3")
    _req(opener, "POST", f"{registry.base_url}/web/users/delete-group", cookie=cookie,
         data={"group": "ИУ7-31"})
    assert not registry.users.has("s1")
    assert not registry.users.has("s2")
    assert registry.users.has("admin")                 # other group untouched
