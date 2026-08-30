import subprocess
import sys
from pathlib import Path

import pytest

# Add the worktree's src directory to sys.path so pytest can import from the local version
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


@pytest.fixture(scope="session")
def base_tar(tmp_path_factory):
    """
    Session-scoped Debian rootfs tarball, exported from a throwaway container.

    Shared across tier3 tests (nspawn runner, base image builder) so the
    image is only pulled/exported once per test session.

    Args:
        tmp_path_factory: Pytest factory for session-scoped temp directories.

    Returns:
        Path to the exported rootfs tarball.

    """
    d = tmp_path_factory.mktemp("base")
    tar = d / "rootfs.tar"
    cid = subprocess.run(
        ["docker", "create", "debian:trixie-slim"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    try:
        subprocess.run(["docker", "export", cid, "-o", str(tar)], check=True)
    finally:
        subprocess.run(["docker", "rm", cid], check=True, capture_output=True)
    return tar
