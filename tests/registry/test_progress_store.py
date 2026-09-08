"""Tier1: server-side per-student progress store."""
import pytest

from hashpass.registry.progress_store import ProgressStore


@pytest.mark.tier1
def test_record_get_all(tmp_path):
    ps = ProgressStore(tmp_path / "progress")
    ps.record("alice", "lab:1", status="passed", ts="T1", global_key="gk", digest="d")
    ps.record("alice", "lab:2", status="failed", ts="T2", digest="d2")
    ps.record("bob", "lab:1", status="passed", ts="T3", global_key="gk2", digest="d")
    alice = ps.get("alice")
    assert alice["lab:1"]["status"] == "passed"
    assert alice["lab:1"]["global_key"] == "gk"
    assert alice["lab:2"]["status"] == "failed"
    assert ps.get("ghost") == {}
    everyone = ps.all()
    assert set(everyone) == {"alice", "bob"}
    assert everyone["bob"]["lab:1"]["status"] == "passed"


@pytest.mark.tier1
def test_record_overwrites(tmp_path):
    ps = ProgressStore(tmp_path / "p")
    ps.record("a", "lab:1", status="failed", ts="T1")
    ps.record("a", "lab:1", status="passed", ts="T2", global_key="gk")
    assert ps.get("a")["lab:1"]["status"] == "passed"
    assert ps.get("a")["lab:1"]["global_key"] == "gk"
