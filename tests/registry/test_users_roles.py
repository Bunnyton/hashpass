"""Tier1: UserStore profiles + roles + legacy-record back-compat."""
import json

import pytest

from hashpass.registry.passwords import UserStore, hash_password


@pytest.mark.tier1
def test_add_with_profile_and_role(tmp_path):
    us = UserStore(tmp_path / "u.json")
    us.add("bob", "pw", role="student", group="ИУ7-11", comment="note")
    assert us.verify("bob", "pw")
    assert not us.verify("bob", "nope")
    prof = us.get("bob")
    assert prof == {"user": "bob", "role": "user", "group": "ИУ7-11",       # spec 2026-10-25 §2
                    "comment": "note", "created_at": prof["created_at"], "auto_approve": False,
                    "tz": "", "perms": None}
    assert "pw" not in prof                    # never leak the hash in a profile
    assert us.role("bob") == "user"


@pytest.mark.tier1
def test_set_role_and_validation(tmp_path):
    us = UserStore(tmp_path / "u.json")
    us.add("bob", "pw")
    assert us.role("bob") == "user"             # default role
    us.set_role("bob", "author")                # a legacy role: an ordinary user
    assert us.role("bob") == "user"
    us.set_role("bob", "admin")
    assert us.role("bob") == "admin"
    with pytest.raises(ValueError, match="unknown role"):
        us.add("x", "pw", role="wizard")
    with pytest.raises(KeyError):
        us.set_role("ghost", "admin")


@pytest.mark.tier1
def test_delete_user(tmp_path):
    us = UserStore(tmp_path / "u.json")
    us.add("bob", "pw", group="G")
    assert us.delete("bob") is True
    assert not us.has("bob")
    assert us.delete("bob") is False


@pytest.mark.tier1
def test_set_password_preserves_profile(tmp_path):
    us = UserStore(tmp_path / "u.json")
    us.add("bob", "old", role="author", group="G", comment="c")
    us.set_password("bob", "new")
    assert not us.verify("bob", "old")
    assert us.verify("bob", "new")
    prof = us.get("bob")
    assert (prof["role"], prof["group"], prof["comment"]) == ("user", "G", "c")
    with pytest.raises(KeyError):
        us.set_password("ghost", "x")


@pytest.mark.tier1
def test_legacy_string_record_normalizes(tmp_path):
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"old": hash_password("pw")}), encoding="utf-8")  # legacy: bare hash str
    us = UserStore(p)
    assert us.verify("old", "pw")
    assert us.role("old") == "user"
    assert us.get("old")["group"] == ""


@pytest.mark.tier1
def test_all_users_sorted_profiles_without_hashes(tmp_path):
    us = UserStore(tmp_path / "u.json")
    us.add("zoe", "pw")
    us.add("amy", "pw")
    users = us.all_users()
    assert [u["user"] for u in users] == ["amy", "zoe"]
    assert all("pw" not in u for u in users)
