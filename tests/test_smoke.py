import pytest

import hashpass


@pytest.mark.tier1
def test_package_imports():
    assert hashpass.__version__ == "0.0.0"
