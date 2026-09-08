import os
import sys
from pathlib import Path

import pytest

# Add the worktree's src directory to sys.path so pytest can import from the local version
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


@pytest.fixture(autouse=True)
def _test_env(monkeypatch) -> None:
    """No launch-time self-update network call, and the engine toolkit is active for tests."""
    monkeypatch.setenv("HASHPASS_NO_UPDATE", "1")
    monkeypatch.setenv("HASHENGINE_ENABLE", "1")


@pytest.fixture(scope="session")
def base_tar() -> Path:
    """
    Return a prepared Debian rootfs tarball for tier3 tests (nspawn runner, base image builder).

    hashpass does not build the base rootfs (no docker dependency); it is prepared out-of-band.
    This fixture reuses one: $HASHPASS_BASE_TAR, else ~/.hashpass/base/rootfs.tar, else skips.
    """
    explicit = os.environ.get("HASHPASS_BASE_TAR")
    candidates = ([Path(explicit)] if explicit else []) + [Path.home() / ".hashpass" / "base" / "rootfs.tar"]
    for tar in candidates:
        if tar.exists():
            return tar
    pytest.skip("no prepared base rootfs (set HASHPASS_BASE_TAR or place ~/.hashpass/base/rootfs.tar)")
    return candidates[-1]  # unreachable (skip raises); keeps the return type honest
