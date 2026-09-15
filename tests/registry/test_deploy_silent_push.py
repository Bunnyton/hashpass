"""
Tier2: replay ./deploy.sh — one login must silence every subsequent push.

`test_pool_token_variants` covers _pool_token in isolation.  These tests drive the real
cli.cmd_* code paths through the live registry fixture, which is what the user actually
runs from content/tasks/deploy.sh.
"""
import getpass as _getpass
import time

import pytest

from hashpass import cli
from hashpass.registry.creds import CredentialCache

_STUB_TOKEN = "LOCAL.TOKEN.STUB"  # noqa: S105 — literal never used as a credential


def _prompt_escaped(prompt: str) -> str:
    """Blow up loudly the moment a "fast path" flow actually asks the user something."""
    msg = f"CLI asked for input we said it wouldn't need: {prompt!r}"
    raise AssertionError(msg)


def _fail_password(_prompt: str = "") -> str:
    """Fail loudly — a cached token flow that reaches getpass has already lost."""
    msg = "password prompt escaped the fast path"
    raise AssertionError(msg)


class _RecordingIo:
    """Records writes; refuses to be read from (a read means the fast path lost)."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, s: str) -> None:
        self.writes.append(s)

    def clock(self) -> str:
        return ""

    def as_io(self) -> cli.Io:
        return cli.Io(read=_prompt_escaped, write=self.write, clock=self.clock)


@pytest.mark.tier2
def test_second_login_is_silent_and_leaves_pool_json_synced(registry, tmp_path, monkeypatch):
    """cmd_login twice against the same URL: run #2 must ask nothing and print `уже вошли`."""
    registry.users.add("bunnyton", "pass123!", role="admin", group="G")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)

    def _read1(prompt: str) -> str:
        return "bunnyton" if "логин" in prompt else ""
    monkeypatch.setattr(_getpass, "getpass", lambda _p="": "pass123!")
    io1 = cli.Io(read=_read1, write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io1) == 0

    # sanity: token cached, pool.json holds the URL under which the token lives.
    assert cli._pool_token(env, registry.base_url) is not None                       # noqa: SLF001

    # run #2: same URL. MUST NOT ask login, MUST NOT ask password.
    recorder = _RecordingIo()
    monkeypatch.setattr(_getpass, "getpass", _fail_password)
    assert cli.cmd_login(env, registry.base_url, recorder.as_io()) == 0
    joined = "".join(recorder.writes)
    assert "уже вошли" in joined, f"expected fast-path message, got: {joined!r}"


@pytest.mark.tier2
def test_push_stays_silent_after_first_login(registry, tmp_path, monkeypatch):
    """Login → local build's creds.json write for a DIFFERENT URL → push still silent."""
    registry.users.add("bunnyton", "pass123!", role="admin", group="G")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)

    def _read1(prompt: str) -> str:
        return "bunnyton" if "логин" in prompt else ""
    monkeypatch.setattr(_getpass, "getpass", lambda _p="": "pass123!")
    io1 = cli.Io(read=_read1, write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io1) == 0

    # simulate `hashengine build` touching creds.json for a DIFFERENT registry key
    # (the local build server at 127.0.0.1:8080).  This must not evict the pool token.
    CredentialCache(env.creds).save(
        "http://127.0.0.1:8080", _STUB_TOKEN, int(time.time()) + 3600,
    )

    # `_ensure_registry_login(env, None, io)` resolves the URL from pool.json and asks
    # the same _cache_hit_or_forget helper as push. MUST NOT prompt anything.
    monkeypatch.setattr(_getpass, "getpass", _fail_password)
    url = cli._ensure_registry_login(env, None, _RecordingIo().as_io())              # noqa: SLF001
    assert url                                                                       # something sensible
