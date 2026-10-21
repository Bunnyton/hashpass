"""Tier1: users under courses -- anyone pushes to their namespace, admin-only search, reserved logins."""
from pathlib import Path

import pytest

from hashpass.registry.passwords import UserStore
from tests.registry.test_push_commit import _http, _Pool


@pytest.mark.tier1
def test_user_role_is_accepted(tmp_path: Path) -> None:
    users = UserStore(tmp_path / "u.json")
    users.add("ann", "pw-correct1", role="user")
    assert users.role("ann") == "user"


@pytest.mark.tier1
def test_a_deleted_login_stays_reserved(tmp_path: Path) -> None:
    users = UserStore(tmp_path / "u.json")
    users.add("ann", "pw-correct1")
    assert users.delete("ann")
    assert users.reserved("ann")
    with pytest.raises(ValueError, match="занят"):
        users.add("ann", "pw-correct1")


@pytest.mark.tier1
def test_any_user_pushes_into_their_own_namespace(registry, tmp_path: Path) -> None:
    pool = _Pool(registry, tmp_path)
    registry.users.add("kid", "pw-correct1", role="student")
    from hashpass.registry.remote import RemoteRegistry  # noqa: PLC0415
    pool.tok["kid"] = RemoteRegistry(pool.url).login("kid", "pw-correct1")
    assert pool.push("kid/my", "1", image="mine", user="kid")[0] == 201  # noqa: PLR2004
    assert pool.begin("bob/lab", "1", user="kid")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_user_search_is_admin_only(registry, tmp_path: Path) -> None:
    pool = _Pool(registry, tmp_path)
    registry.users.add("stud1", "pw-correct1", role="student", comment="ИТ-21 староста")
    registry.users.add("stud2", "pw-correct1", role="student", comment="ИТ-22")
    code, body = _http("GET", f"{pool.url}/users/search?q=%D0%B8%D1%82-21", token=pool.tok["bunnyton"])
    assert code == 200  # noqa: PLR2004
    assert [u["user"] for u in body["users"]] == ["stud1"]
    assert _http("GET", f"{pool.url}/users/search?q=x", token=pool.tok["bob"])[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_register_refuses_a_reserved_login(registry) -> None:
    registry.users.add("gone", "pw-correct1")
    registry.users.delete("gone")
    code, _ = _http("POST", f"{registry.base_url}/register",
                    body={"user": "gone", "password": "Strong-pass-1"})
    assert code == 409  # noqa: PLR2004
