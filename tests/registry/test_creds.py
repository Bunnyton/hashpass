import stat

import pytest

from hashpass.registry.creds import CredentialCache

_NOW = 1000.0
_EXPIRY = 2000


@pytest.mark.tier1
def test_cache_file_is_owner_only(tmp_path):
    # The cache holds a live 7-day bearer token — it must not be world-readable (§5).
    cache = CredentialCache(tmp_path / "creds.json")
    cache.save("http://reg", "tok-123", _EXPIRY)
    assert stat.S_IMODE((tmp_path / "creds.json").stat().st_mode) == 0o600  # noqa: PLR2004


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


@pytest.mark.tier1
def test_forget_variants_removes_only_matching_entries_and_counts_them(tmp_path):
    cache = CredentialCache(tmp_path / "creds.json")
    cache.save("http://reg", "tok-123", _EXPIRY)
    cache.save("https://reg", "tok-456", _EXPIRY)
    cache.save("http://other", "tok-789", _EXPIRY)
    removed = cache.forget_variants(["http://reg", "https://reg", "http://reg/"])
    assert removed == 2   # noqa: PLR2004 -- only the 2 that existed
    assert cache.cached_token("http://reg", now=_NOW) is None
    assert cache.cached_token("https://reg", now=_NOW) is None
    assert cache.cached_token("http://other", now=_NOW) == "tok-789"  # untouched


@pytest.mark.tier1
def test_forget_variants_on_empty_cache_returns_zero(tmp_path):
    cache = CredentialCache(tmp_path / "creds.json")
    assert cache.forget_variants(["http://reg", "https://reg"]) == 0
