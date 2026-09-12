"""Tier2: a valid token/cookie for a user the admin has just deleted is refused everywhere."""
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_k) -> None:  # noqa: ANN002, ANN003
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def _req(opener, method, url, *, cookie=None, data=None) -> tuple:
    headers = {"Cookie": cookie} if cookie else {}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
    try:
        resp = opener.open(req, timeout=10)
        return resp.status, resp.headers, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode("utf-8", "replace")


@pytest.mark.tier2
def test_deleted_students_bearer_token_stops_working(registry):
    """A student whose account was just deleted cannot /submit even with a still-valid token."""
    client = RemoteRegistry(registry.base_url)
    token = client.register("stud", "pass123!", group="G")
    # sanity: /me works while the account exists
    me_req = urllib.request.Request(  # noqa: S310
        f"{registry.base_url}/me", headers={"Authorization": f"Bearer {token}"})
    assert urllib.request.build_opener(urllib.request.ProxyHandler({})).open(me_req).status == HTTPStatus.OK
    # admin deletes the student
    registry.users.delete("stud")
    # now every token-authed endpoint should refuse (401) -- token still signed OK, but no user
    for path in ("/me", "/catalog", "/progress", "/images"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                urllib.request.Request(  # noqa: S310
                    f"{registry.base_url}{path}", headers={"Authorization": f"Bearer {token}"}))
        assert exc.value.code == HTTPStatus.UNAUTHORIZED, f"{path}: got {exc.value.code}"
    # and /submit for a ghost user must NOT write any progress
    with pytest.raises(urllib.error.HTTPError) as exc:
        client.submit("lab:1", "any-digest", passed=True, token=token)
    assert exc.value.code == HTTPStatus.UNAUTHORIZED


@pytest.mark.tier2
def test_deleted_admins_web_cookie_stops_working(registry):
    """A deleted admin's cookie session no longer opens /web/* pages -- they redirect to login."""
    registry.users.add("admin", "pass123!", role="admin", group="")
    registry.users.add("other", "pass123!", role="admin", group="")
    opener = _opener()
    _, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login",
                         data={"user": "admin", "password": "pass123!"})
    cookie = headers["Set-Cookie"].split(";")[0]
    # sanity: /web works with the cookie
    assert _req(opener, "GET", f"{registry.base_url}/web", cookie=cookie)[0] == HTTPStatus.OK
    # the OTHER admin deletes them
    registry.users.delete("admin")
    # cookie is still cryptographically valid, but the account is gone -> redirect to login
    status, redir_headers, _ = _req(opener, "GET", f"{registry.base_url}/web", cookie=cookie)
    assert status == HTTPStatus.SEE_OTHER
    assert redir_headers["Location"] == "/web/login"
