"""Tier1: AttemptStore -- one file per console session, seq-gated appends, caps, rotation."""
# ruff: noqa: PLR2004, PT011
import pytest

from hashpass.registry.attempt_store import (
    AttemptStore,
    SeqMismatch,
    is_live,
    sanitize_entries,
)

SID = "a" * 32


def _e(cmd: str, out: str = "") -> dict:
    return {"command": cmd, "output": out, "ts": "t", "typing": 1.0, "pasted": False}


@pytest.mark.tier1
def test_append_in_order_and_seq_mismatch(tmp_path):
    st = AttemptStore(tmp_path)
    assert st.append("u", "ns/x:1", SID, 0, [_e("ls", "a\n"), _e("pwd", "/\n")], now=10) == 2
    with pytest.raises(SeqMismatch) as err:
        st.append("u", "ns/x:1", SID, 0, [_e("ls")], now=11)
    assert err.value.have == 2
    assert st.append("u", "ns/x:1", SID, 2, [_e("id")], now=12) == 3
    (rec,) = st.sessions("u", "ns/x:1")
    assert [e["command"] for e in rec["entries"]] == ["ls", "pwd", "id"]
    assert rec["entries"][0]["output"] == "a\n"
    assert rec["ref"] == "ns/x:1"
    assert rec["started"] == 10
    assert rec["updated"] == 12


@pytest.mark.tier1
def test_output_capped_and_session_truncated(tmp_path):
    big = "x" * (20 * 1024)
    (entry,) = sanitize_entries([_e("cat big", big)])
    assert len(entry["output"]) < 17 * 1024
    assert entry["output"].endswith("…обрезано")
    st = AttemptStore(tmp_path)
    seq = 0
    for _ in range(40):                      # 40 x 16 KiB > 512 KiB
        seq = st.append("u", "r:1", SID, seq, [_e("cat big", big)], now=1)
    (rec,) = st.sessions("u", "r:1")
    assert rec["truncated"] is True
    assert sum(len(e["output"]) for e in rec["entries"]) <= 512 * 1024


@pytest.mark.tier1
def test_rotation_keeps_passed(tmp_path):
    st = AttemptStore(tmp_path)
    st.append("u", "r:1", "f" * 32, 0, [_e("good")], now=0)
    st.finish("u", "r:1", "f" * 32, "passed", now=0)
    for i in range(31):
        st.append("u", "r:1", f"{i:032x}", 0, [_e(f"try{i}")], now=i + 1)
    sessions = st.sessions("u", "r:1")
    assert len([s for s in sessions if s["final"] != "passed"]) == 30
    assert "0" * 32 not in {s["session_id"] for s in sessions}   # oldest attempt dropped
    assert st.solution("u", "r:1")["session_id"] == "f" * 32


@pytest.mark.tier1
def test_solutions_summary_and_live(tmp_path):
    st = AttemptStore(tmp_path)
    st.append("u", "r:1", SID, 0, [_e("ls")], now=100)
    assert is_live(st.sessions("u", "r:1")[0], now=150)
    assert not is_live(st.sessions("u", "r:1")[0], now=161)
    st.finish("u", "r:1", SID, "passed", now=120)
    assert st.solutions("u") == {"r:1": {"session_id": SID, "at": 120}}
    assert st.summary("u", now=130)["r:1"] == {"sessions": 1, "passed": True, "live": False}
    st.delete_user("u")
    assert st.sessions("u", "r:1") == []


@pytest.mark.tier1
def test_bad_session_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        AttemptStore(tmp_path).append("u", "r:1", "../etc", 0, [_e("ls")])
