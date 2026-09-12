import pytest

import hashengine.cli
import hashpass
import hashpass.student_cli


@pytest.mark.tier1
def test_package_imports():
    assert hashpass.__version__ == "0.2.4"


@pytest.mark.tier1
def test_cli_entry_points_import():
    # both front ends import cleanly and expose a main()
    assert callable(hashengine.cli.main)
    assert callable(hashpass.student_cli.main)
