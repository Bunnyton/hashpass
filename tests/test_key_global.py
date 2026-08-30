import pytest

from hashpass.key import global_key, local_key

_SECRET = b"server-secret-XYZ"
_OTHER_SECRET = b"different-secret"


@pytest.mark.tier1
def test_global_key_deterministic():
    first = global_key(_SECRET, "alice", "task1")
    second = global_key(_SECRET, "alice", "task1")
    assert first == second
    assert first.startswith("gkey{")


@pytest.mark.tier1
def test_global_key_requires_secret():
    # Unforgeable: a different server_secret yields a different key.
    assert global_key(_SECRET, "alice", "task1") != global_key(_OTHER_SECRET, "alice", "task1")


@pytest.mark.tier1
def test_global_key_identity_bound_and_nul_delimited():
    assert global_key(_SECRET, "alice", "task1") != global_key(_SECRET, "bob", "task1")
    # NUL delimiter prevents (student_id || task_id) concatenation collisions.
    assert global_key(_SECRET, "al", "icetask") != global_key(_SECRET, "alice", "task")


@pytest.mark.tier1
def test_local_key_unchanged_distinct_namespace():
    lk = local_key("task1", 0, "nonce1")
    assert lk.startswith("key{")
    assert not lk.startswith("gkey{")


@pytest.mark.tier1
def test_global_key_rejects_nul_in_ids():
    with pytest.raises(ValueError, match="NUL"):
        global_key(_SECRET, "a\x00b", "task1")
    with pytest.raises(ValueError, match="NUL"):
        global_key(_SECRET, "alice", "t\x00")
