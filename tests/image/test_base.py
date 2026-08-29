import pytest

from hashpass.image.base import build_base


@pytest.mark.tier3
def test_build_base_has_runtime(tmp_path, base_tar):  # base_tar fixture reused via conftest
    base = build_base(tmp_path / "base", from_tar=base_tar)
    assert (base / "usr/bin/hash").exists()
    assert (base / ".hash").is_dir()
