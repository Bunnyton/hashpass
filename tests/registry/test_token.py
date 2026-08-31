import secrets

import pytest

from hashpass.registry.token import issue_token, token_expiry, verify_token

_KEY = secrets.token_bytes(32)
_NOW = 1000.0
_DAY = 24 * 60 * 60
_WEEK = 7 * _DAY


@pytest.mark.tier1
def test_token_valid_within_ttl():
    token = issue_token(_KEY, "alice", now=_NOW)
    assert verify_token(_KEY, token, now=_NOW) == "alice"
    assert verify_token(_KEY, token, now=_NOW + 6 * _DAY) == "alice"


@pytest.mark.tier1
def test_token_expires_at_ttl_boundary():
    token = issue_token(_KEY, "alice", now=_NOW)
    assert verify_token(_KEY, token, now=_NOW + _WEEK) is None
    assert verify_token(_KEY, token, now=_NOW + _WEEK + _DAY) is None


@pytest.mark.tier1
def test_token_rejects_wrong_secret_and_tampering():
    token = issue_token(_KEY, "alice", now=_NOW)
    assert verify_token(secrets.token_bytes(32), token, now=_NOW) is None
    assert verify_token(_KEY, token + "x", now=_NOW) is None
    assert verify_token(_KEY, "not-base64!!", now=_NOW) is None


@pytest.mark.tier1
def test_token_expiry_is_readable_without_secret():
    token = issue_token(_KEY, "alice", now=_NOW)
    assert token_expiry(token) == int(_NOW) + _WEEK
    assert token_expiry("garbage") is None


@pytest.mark.tier1
def test_token_custom_ttl():
    token = issue_token(_KEY, "eve", now=0.0, ttl=10)
    assert verify_token(_KEY, token, now=9.0) == "eve"
    assert verify_token(_KEY, token, now=10.0) is None


@pytest.mark.tier1
def test_token_rejects_nul_user():
    with pytest.raises(ValueError, match="NUL"):
        issue_token(_KEY, "a\x00b", now=_NOW)
