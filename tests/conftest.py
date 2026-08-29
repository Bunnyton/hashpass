import subprocess

import pytest


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
    subprocess.run(["docker", "export", cid, "-o", str(tar)], check=True)
    subprocess.run(["docker", "rm", cid], check=True, capture_output=True)
    return tar
