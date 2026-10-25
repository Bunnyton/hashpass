"""Tier1: pool roles are user and admin; an admin carries permission boxes (spec 2026-10-25 §1-§2)."""
import json
from pathlib import Path

import pytest

from hashpass.registry import perms
from hashpass.registry.passwords import UserStore


def _store(tmp_path: Path, raw: dict) -> UserStore:
    path = tmp_path / "users.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return UserStore(path)


def _rec(role: str, created: float = 1.0, **extra: object) -> dict:
    return {"pw": "x", "role": role, "group": "", "comment": "", "created_at": created, **extra}


@pytest.mark.tier1
def test_legacy_roles_read_as_user(tmp_path: Path) -> None:
    users = _store(tmp_path, {"a": _rec("author"), "s": _rec("student"), "u": _rec("user")})
    assert [users.role(u) for u in ("a", "s", "u")] == ["user", "user", "user"]


@pytest.mark.tier1
def test_an_admin_without_perms_has_all(tmp_path: Path) -> None:
    users = _store(tmp_path, {"admin": _rec("admin", 1.0), "bob": _rec("admin", 2.0)})
    assert perms.pool_perms(users, "", "bob") == perms.ALL


@pytest.mark.tier1
def test_a_new_admin_gets_the_default(tmp_path: Path) -> None:
    users = _store(tmp_path, {"admin": _rec("admin"), "kid": _rec("student")})
    users.set_role("kid", "admin")
    assert perms.pool_perms(users, "", "kid") == perms.DEFAULT
    users.set_role("kid", "user")
    assert perms.pool_perms(users, "", "kid") == frozenset()
    assert users.get("kid")["perms"] is None


@pytest.mark.tier1
def test_the_only_admin_is_the_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HASHPASS_ADMIN", raising=False)
    users = _store(tmp_path, {"zed": _rec("admin", 5.0, perms=[]), "amy": _rec("admin", 9.0, perms=[])})
    assert perms.pool_owner(users, "") == "zed"                 # no `admin` login: the earliest admin
    assert perms.pool_perms(users, "", "zed") == perms.ALL       # the owner's boxes cannot be taken
    assert perms.pool_perms(users, "", "amy") == frozenset()
    assert perms.pool_owner(users, "amy") == "amy"               # config.json names the owner
    users2 = _store(tmp_path, {"admin": _rec("admin", 9.0), "zed": _rec("admin", 5.0)})
    assert perms.pool_owner(users2, "") == "admin"               # $HASHPASS_ADMIN, by default `admin`


@pytest.mark.tier1
def test_clean_drops_unknown_keys() -> None:
    assert perms.clean(["content", "root", "progress"], default=perms.DEFAULT) == {"content", "progress"}
    assert perms.clean(None, default=perms.DEFAULT) == perms.DEFAULT
    assert perms.KEYS == ("admins", "content", "people", "progress")
    assert {"content", "people", "progress"} == perms.DEFAULT


@pytest.mark.tier1
def test_set_perms_keeps_only_known_keys(tmp_path: Path) -> None:
    users = _store(tmp_path, {"admin": _rec("admin"), "bob": _rec("admin", 2.0)})
    users.set_perms("bob", ["people", "bogus"])
    assert users.get("bob")["perms"] == ["people"]
    assert perms.pool_perms(users, "", "bob") == {"people"}


@pytest.mark.tier2
def test_me_carries_the_effective_boxes(registry) -> None:
    from hashpass.registry.remote import RemoteRegistry  # noqa: PLC0415
    registry.users.add("admin", "pw-correct1", role="admin")
    registry.users.add("ed", "pw-correct1", role="admin")
    registry.users.set_perms("ed", ["content"])
    client = RemoteRegistry(registry.base_url)
    assert client.me(token=client.login("admin", "pw-correct1"))["perms"] == list(perms.KEYS)  # the owner
    assert client.me(token=client.login("ed", "pw-correct1"))["perms"] == ["content"]
