"""Tier1: `_pool_token` finds a cached token even when the URL is written differently."""
import time
from pathlib import Path

import pytest

from hashpass import cli
from hashpass.registry.creds import CredentialCache


@pytest.fixture
def env(tmp_path: Path):
    (tmp_path / ".hashpass").mkdir()
    return cli.build_env({"HASHPASS_HOME": str(tmp_path / ".hashpass")}, default_home=tmp_path)


@pytest.mark.tier1
@pytest.mark.parametrize(("stored", "looked_up"), [
    ("https://135.106.177.228:8080", "135.106.177.228:8080"),         # scheme lost
    ("https://135.106.177.228:8080", "https://135.106.177.228:8080/"),  # trailing slash
    ("https://135.106.177.228:8080", "http://135.106.177.228:8080"),   # wrong scheme
    ("135.106.177.228:8080",         "https://135.106.177.228:8080"),  # scheme added
    ("http://127.0.0.1:9",           "127.0.0.1:9"),                   # local
])
def test_pool_token_finds_token_across_url_variants(env, stored, looked_up):
    """A token cached under `stored` must be reachable via `_pool_token(env, looked_up)`."""
    stored_token = "AAA.BBB.CCC"                              # noqa: S105  (opaque test fixture)
    CredentialCache(env.creds).save(stored, stored_token, int(time.time()) + 3600)
    assert cli._pool_token(env, looked_up) == stored_token   # noqa: SLF001


@pytest.mark.tier1
def test_pool_token_returns_none_for_unrelated_url(env):
    """A cached token for `A` must NOT come back when the lookup is for a different host."""
    CredentialCache(env.creds).save("https://A", "TOKA", int(time.time()) + 3600)
    assert cli._pool_token(env, "https://B") is None      # noqa: SLF001
