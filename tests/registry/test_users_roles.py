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
    assert prof == {"user": "bob", "role": "student", "group": "ИУ7-11",
                    "comment": "note", "created_at": prof["created_at"]}
    assert "pw" not in prof                    # never leak the hash in a profile
    assert us.role("bob") == "student"


@pytest.mark.tier1
def test_set_role_and_validation(tmp_path):
    us = UserStore(tmp_path / "u.json")
    us.add("bob", "pw")
    assert us.role("bob") == "student"          # default role
    us.set_role("bob", "author")
    assert us.role("bob") == "author"
    with pytest.raises(ValueError, match="unknown role"):
        us.add("x", "pw", role="wizard")
    with pytest.raises(KeyError):
        us.set_role("ghost", "admin")


@pytest.mark.tier1
def test_legacy_string_record_normalizes(tmp_path):
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"old": hash_password("pw")}), encoding="utf-8")  # legacy: bare hash str
    us = UserStore(p)
    assert us.verify("old", "pw")
    assert us.role("old") == "student"
    assert us.get("old")["group"] == ""


@pytest.mark.tier1
def test_all_users_sorted_profiles_without_hashes(tmp_path):
    us = UserStore(tmp_path / "u.json")
    us.add("zoe", "pw")
    us.add("amy", "pw")
    users = us.all_users()
    assert [u["user"] for u in users] == ["amy", "zoe"]
    assert all("pw" not in u for u in users)
