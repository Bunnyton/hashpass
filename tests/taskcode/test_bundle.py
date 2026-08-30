"""Tests for bundle.py: dump/load/apply split config bundle."""
import pytest

from hashpass.canon import FileState
from hashpass.taskcode.bundle import Bundle, apply_bundle, dump_bundle, load_bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks


def _bundle() -> Bundle:
    checks = DerivedChecks(
        task_id="demo",
        stages=(
            StageChecks(
                canonical={"result.txt": FileState("file", "answer\n"),
                           "<output>": FileState("file", "")},
                mode="line",
                threshold=1.0,
            ),
        ),
    )
    conditions = {0: {"deny": ["rm"], "require_flags": ["-l"], "mention": ["sort"]}}
    hints = {0: [{"trigger": "cat", "message": "use ls first"}]}
    return Bundle(checks=checks, conditions=conditions, hints=hints)


@pytest.mark.tier1
def test_bundle_round_trip(tmp_path):
    bundle = _bundle()
    dump_bundle(bundle, tmp_path / "b")
    assert load_bundle(tmp_path / "b") == bundle   # checks + conditions + hints all round-trip


@pytest.mark.tier1
def test_apply_bundle_lands_under_hash_task(tmp_path):
    dump_bundle(_bundle(), tmp_path / "b")
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    apply_bundle(tmp_path / "b", rootfs)
    for name in ("checks.json", "conditions.toml", "hints.toml"):
        assert (rootfs / ".hash" / ".task" / name).is_file()
