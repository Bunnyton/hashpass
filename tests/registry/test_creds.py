import pytest

from hashpass.registry.creds import CredentialCache

_NOW = 1000.0
_EXPIRY = 2000


@pytest.mark.tier1
def test_empty_cache_returns_none(tmp_path):
    cache = CredentialCache(tmp_path / "creds.json")
    assert cache.cached_token("http://reg", now=_NOW) is None


@pytest.mark.tier1
def test_cache_returns_live_token_until_expiry(tmp_path):
    cache = CredentialCache(tmp_path / "creds.json")
    cache.save("http://reg", "tok-123", _EXPIRY)
    assert cache.cached_token("http://reg", now=_NOW) == "tok-123"
    assert cache.cached_token("http://reg", now=float(_EXPIRY) - 1) == "tok-123"
    assert cache.cached_token("http://reg", now=float(_EXPIRY)) is None


@pytest.mark.tier1
def test_cache_is_per_registry_and_persisted(tmp_path):
    path = tmp_path / "creds.json"
    cache = CredentialCache(path)
    cache.save("http://reg", "tok-123", _EXPIRY)
    assert cache.cached_token("http://other", now=_NOW) is None
    assert CredentialCache(path).cached_token("http://reg", now=_NOW) == "tok-123"
