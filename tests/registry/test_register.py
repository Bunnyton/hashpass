"""Tier2: /register, /me, and admin gating over the live server via RemoteRegistry."""
import urllib.error
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry


@pytest.mark.tier2
def test_register_creates_student_and_me(registry):
    c = RemoteRegistry(registry.base_url)
    token = c.register("stud", "pw", group="ИУ7-31", comment="hi")
    assert token
    assert registry.users.role("stud") == "student"
    me = c.me(token=token)
    assert me["user"] == "stud"
    assert me["role"] == "student"
    assert me["group"] == "ИУ7-31"
    assert me["comment"] == "hi"


@pytest.mark.tier2
def test_register_requires_group(registry):
    c = RemoteRegistry(registry.base_url)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.register("s2", "pw", group="")
    assert exc.value.code == HTTPStatus.BAD_REQUEST


@pytest.mark.tier2
def test_register_duplicate_conflicts(registry):
    c = RemoteRegistry(registry.base_url)
    c.register("dup", "pw", group="G")
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.register("dup", "pw2", group="G")
    assert exc.value.code == HTTPStatus.CONFLICT


@pytest.mark.tier2
def test_register_closed_is_forbidden(registry):
    registry.users.add("admin", "pw", role="admin")
    c = RemoteRegistry(registry.base_url)
    admin_token = c.login("admin", "pw")
    c.set_registration(open_=False, token=admin_token)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.register("late", "pw", group="G")
    assert exc.value.code == HTTPStatus.FORBIDDEN


@pytest.mark.tier2
def test_admin_cannot_change_own_role_via_api(registry):
    registry.users.add("admin", "pw", role="admin")
    c = RemoteRegistry(registry.base_url)
    tok = c.login("admin", "pw")
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.set_role("admin", "student", token=tok)
    assert exc.value.code == HTTPStatus.FORBIDDEN
    assert registry.users.role("admin") == "admin"


@pytest.mark.tier1
def test_open_wraps_connection_failure():
    c = RemoteRegistry("http://127.0.0.1:1")   # nothing listening -> a clear error, not raw errno
    with pytest.raises(RuntimeError, match="не удалось подключиться"):
        c.catalog(token="x")  # noqa: S106


@pytest.mark.tier2
def test_me_rejects_bad_token(registry):
    c = RemoteRegistry(registry.base_url)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.me(token="not-a-real-token")  # noqa: S106  (bad token literal for the 401 path)
    assert exc.value.code == HTTPStatus.UNAUTHORIZED


@pytest.mark.tier2
def test_admin_endpoints_are_role_gated(registry):
    c = RemoteRegistry(registry.base_url)
    registry.users.add("admin", "pw", role="admin")
    admin_token = c.login("admin", "pw")
    c.register("st", "pw", group="G")
    # admin can grant a role
    c.set_role("st", "author", token=admin_token)
    assert registry.users.role("st") == "author"
    # a non-admin (student) token -> 403
    student_token = c.register("st2", "pw", group="G")
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.set_registration(open_=False, token=student_token)
    assert exc.value.code == HTTPStatus.FORBIDDEN
    # a bogus/absent token -> 401
    with pytest.raises(urllib.error.HTTPError) as exc2:
        c.set_role("st", "admin", token="bogus")  # noqa: S106  (bad token literal for the 401 path)
    assert exc2.value.code == HTTPStatus.UNAUTHORIZED
