import pytest

from hashpass.image.base import build_base


@pytest.mark.tier3
def test_build_base_has_runtime(tmp_path, base_tar):  # base_tar fixture reused via conftest
    base = build_base(tmp_path / "base", from_tar=base_tar)
    assert (base / "usr/bin/hash").exists()
    assert (base / ".hash").is_dir()


@pytest.mark.tier3
def test_build_base_is_bootable(tmp_path, base_tar):
    base = build_base(tmp_path / "base", from_tar=base_tar)
    # systemd installed -> base can be booted with `systemd-nspawn -b`
    assert (base / "lib/systemd/systemd").exists()
    # procps installed -> process tasks have ps/pgrep
    assert (base / "usr/bin/pgrep").exists()
    # fish installed -> the interactive shell is available
    assert (base / "usr/bin/fish").exists()


@pytest.mark.tier3
def test_build_base_skips_when_already_complete(tmp_path, base_tar):
    # A complete base (both systemd + runtime markers) is reused, not re-extracted.
    dest = tmp_path / "base"
    build_base(dest, from_tar=base_tar)
    mtime = (dest / "lib/systemd/systemd").stat().st_mtime
    build_base(dest, from_tar=base_tar)  # second call must be a no-op
    assert (dest / "lib/systemd/systemd").stat().st_mtime == mtime


@pytest.mark.tier3
def test_build_base_rebuilds_a_stale_base(tmp_path, base_tar):
    # A legacy pre-systemd base (runtime marker only) must be wiped + rebuilt bootable,
    # not short-circuited (the bug that made `hashpass run` execute unbooted with no ps).
    dest = tmp_path / "base"
    (dest / "usr/bin").mkdir(parents=True)
    (dest / "usr/bin/hash").write_text("x", encoding="utf-8")
    build_base(dest, from_tar=base_tar)
    assert (dest / "lib/systemd/systemd").exists()
    assert (dest / "usr/bin/pgrep").exists()
