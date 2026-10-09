"""Tier2: /register, /me, and admin gating over the live server via RemoteRegistry."""
import json
import urllib.error
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry


@pytest.mark.tier2
def test_register_creates_student_and_me(registry):
    c = RemoteRegistry(registry.base_url)
    token = c.register("stud", "pass123!", group="ИУ7-31", comment="hi")
    assert token
    assert registry.users.role("stud") == "student"
    me = c.me(token=token)
    assert me["user"] == "stud"
    assert me["role"] == "student"
    assert me["group"] == "ИУ7-31"
    assert me["comment"] == "hi"


@pytest.mark.tier2
def test_register_group_is_optional(registry):
    """Registration succeeds without a group (server-side metadata, editable later)."""
    c = RemoteRegistry(registry.base_url)
    tok = c.register("s2", "pass123!", group="")
    assert tok
    assert registry.users.has("s2")
    assert registry.users.get("s2")["group"] == ""


@pytest.mark.tier2
def test_register_rejects_weak_password(registry):
    c = RemoteRegistry(registry.base_url)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.register("weak", "short", group="G")   # fails the password policy
    assert exc.value.code == HTTPStatus.BAD_REQUEST
    assert "пароль" in json.loads(exc.value.read())["error"]   # the policy reason travels back
    assert not registry.users.has("weak")


@pytest.mark.tier2
def test_register_duplicate_conflicts(registry):
    c = RemoteRegistry(registry.base_url)
    c.register("dup", "pass123!", group="G")
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.register("dup", "pass456!", group="G")
    assert exc.value.code == HTTPStatus.CONFLICT


@pytest.mark.tier2
def test_register_closed_is_forbidden(registry):
    registry.users.add("admin", "pw", role="admin")
    c = RemoteRegistry(registry.base_url)
    admin_token = c.login("admin", "pw")
    c.set_registration(open_=False, token=admin_token)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.register("late", "pass123!", group="G")
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
    c.register("st", "pass123!", group="G")
    # admin can grant a role
    c.set_role("st", "author", token=admin_token)
    assert registry.users.role("st") == "author"
    # a non-admin (student) token -> 403
    student_token = c.register("st2", "pass123!", group="G")
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.set_registration(open_=False, token=student_token)
    assert exc.value.code == HTTPStatus.FORBIDDEN
    # a bogus/absent token -> 401
    with pytest.raises(urllib.error.HTTPError) as exc2:
        c.set_role("st", "admin", token="bogus")  # noqa: S106  (bad token literal for the 401 path)
    assert exc2.value.code == HTTPStatus.UNAUTHORIZED


@pytest.mark.tier2
def test_register_bad_login_says_so(registry):
    """A login the pool cannot store (Cyrillic, spaces, @) is reported as a LOGIN problem."""
    c = RemoteRegistry(registry.base_url)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.register("Иван Петров", "pass123!", group="G")
    assert exc.value.code == HTTPStatus.BAD_REQUEST
    assert "логин" in json.loads(exc.value.read())["error"]


@pytest.mark.tier2
def test_interactive_register_bad_login_does_not_loop_on_password(registry, monkeypatch):
    """Was: every 400 read as «Пароль слишком слабый» -> endless password prompts (Arch report)."""
    from hashpass import cli  # noqa: PLC0415
    asked: list[str] = []
    monkeypatch.setattr(cli.getpass, "getpass", lambda p: asked.append(p) or "pass123!")
    io = cli.Io(read=lambda _p: "", write=lambda _s: None, clock=lambda: "")
    with pytest.raises(RuntimeError, match="логин"):
        cli._register_interactive(RemoteRegistry(registry.base_url), "Иван", io,  # noqa: SLF001
                                  password="pass123!")  # noqa: S106
    assert asked == []          # the reused password is not re-asked: the LOGIN is the problem


@pytest.mark.tier1
def test_validate_login():
    from hashpass.registry.passwords import BadLoginError, validate_login  # noqa: PLC0415
    validate_login("ivan.petrov-1_2")
    for bad in ("", "Иван", "a b", "me@x", "x" * 65):
        with pytest.raises(BadLoginError):
            validate_login(bad)


@pytest.mark.tier1
def test_login_prompt_reasks_on_full_name_in_cyrillic():
    """«Никитин В. Н.» is re-asked with a reason (spaces); a Latin login then goes through."""
    from hashpass import cli  # noqa: PLC0415
    answers = iter(["Никитин В. Н.", "Никитин", "nikitin.vn"])
    out: list[str] = []
    io = cli.Io(read=lambda _p: next(answers), write=out.append, clock=lambda: "")
    assert cli._read_login(io) == "nikitin.vn"  # noqa: SLF001
    text = "".join(out)
    assert "не должно быть пробелов" in text and "латиницей" in text and "nikitin.vn" in text
