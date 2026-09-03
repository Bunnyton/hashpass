import pytest

from hashpass.registry.passwords import UserStore, hash_password, verify_password

_RECORD_FIELDS = 4


@pytest.mark.tier1
def test_hash_and_verify_roundtrip():
    record = hash_password("hunter2")
    assert record.startswith("pbkdf2_sha256$600000$")
    assert len(record.split("$")) == _RECORD_FIELDS
    assert verify_password("hunter2", record) is True
    assert verify_password("wrong", record) is False


@pytest.mark.tier1
def test_verify_rejects_malformed_record():
    assert verify_password("x", "garbage") is False
    assert verify_password("x", "md5$1$aa$bb") is False


@pytest.mark.tier1
def test_has_reports_registration(tmp_path):
    # `has` drives auto-register-on-first-login: unknown users are added, known ones kept.
    store = UserStore(tmp_path / "users.json")
    assert store.has("dev") is False
    store.add("dev", "pw")
    assert store.has("dev") is True


@pytest.mark.tier1
def test_hash_uses_random_salt():
    assert hash_password("hunter2") != hash_password("hunter2")


@pytest.mark.tier1
def test_hash_is_deterministic_with_fixed_salt():
    a = hash_password("pw", iterations=1000, salt=b"0123456789abcdef")
    b = hash_password("pw", iterations=1000, salt=b"0123456789abcdef")
    assert a == b
    assert verify_password("pw", a) is True


@pytest.mark.tier1
def test_user_store_add_verify_persist_replace(tmp_path):
    path = tmp_path / "users.json"
    store = UserStore(path)
    store.add("alice", "s3cr3t")
    assert store.verify("alice", "s3cr3t") is True
    assert store.verify("alice", "nope") is False
    assert store.verify("bob", "whatever") is False
    assert UserStore(path).verify("alice", "s3cr3t") is True  # persisted
    store.add("alice", "rotated")
    assert UserStore(path).verify("alice", "rotated") is True
    assert UserStore(path).verify("alice", "s3cr3t") is False
