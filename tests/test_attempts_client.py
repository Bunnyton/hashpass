"""Tier1: the client side of console sessions -- streaming, resync, outbox, solutions sync."""
# ruff: noqa: S106, ANN202, PLR0913, EM101, TRY003
import io
import json
import urllib.error

import pytest

from hashpass.attempts import (
    AttemptUploader,
    flush_outbox,
    load_solution,
    save_solution,
    solution_text,
    sync_solutions,
)


def _http(code: int, body: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps(body or {}).encode()))


class _Pool:
    """A fake pool: keeps sessions like the server (seq-gated), can go offline or be old."""

    def __init__(self) -> None:
        self.sessions: dict[str, list] = {}
        self.finals: dict[str, str] = {}
        self.offline = False
        self.old = False
        self.drop_reply = False

    def attempt(self, ref, sid, seq, entries, *, final=None, token):  # noqa: ARG002
        if self.old:
            raise _http(404)
        if self.offline:
            raise urllib.error.URLError("down")
        have = self.sessions.setdefault(sid, [])
        if seq != len(have):
            raise _http(409, {"length": len(have)})
        have.extend(entries)
        if final:
            self.finals[sid] = final
        if self.drop_reply:
            self.drop_reply = False
            raise urllib.error.URLError("reply lost")
        return {"length": len(have)}


def _cmd(n: int) -> dict:
    return {"command": f"c{n}", "output": f"o{n}\n", "ts": "t", "typing": 1.0, "pasted": False}


@pytest.mark.tier1
def test_pushes_new_entries_in_order(tmp_path):
    pool, hist = _Pool(), []
    up = AttemptUploader(pool, "r:1", hist, token="t", outbox=tmp_path / "ob")
    hist += [_cmd(0), _cmd(1)]
    assert up.push()
    hist.append(_cmd(2))
    up.close("abandoned")
    assert [e["command"] for e in pool.sessions[up.session_id]] == ["c0", "c1", "c2"]
    assert pool.finals[up.session_id] == "abandoned"


@pytest.mark.tier1
def test_lost_reply_does_not_duplicate(tmp_path):
    pool, hist = _Pool(), [_cmd(0)]
    up = AttemptUploader(pool, "r:1", hist, token="t", outbox=tmp_path / "ob")
    pool.drop_reply = True
    assert not up.push()                  # applied on the pool, but we never heard back
    hist.append(_cmd(1))
    up.close("abandoned")
    assert [e["command"] for e in pool.sessions[up.session_id]] == ["c0", "c1"]


@pytest.mark.tier1
def test_offline_goes_to_outbox_then_flushes(tmp_path):
    pool, hist = _Pool(), [_cmd(0)]
    up = AttemptUploader(pool, "r:1", hist, token="t", outbox=tmp_path / "ob")
    assert up.push()
    pool.offline = True
    hist.append(_cmd(1))
    up.close("abandoned")
    assert len(list((tmp_path / "ob").glob("*.json"))) == 1
    pool.offline = False
    assert flush_outbox(pool, tmp_path / "ob", "t") == 1
    assert [e["command"] for e in pool.sessions[up.session_id]] == ["c0", "c1"]
    assert not list((tmp_path / "ob").glob("*.json"))


@pytest.mark.tier1
def test_old_pool_is_silent(tmp_path):
    pool = _Pool()
    pool.old = True
    up = AttemptUploader(pool, "r:1", [_cmd(0)], token="t", outbox=tmp_path / "ob")
    up.close("abandoned")
    assert up.disabled
    assert not (tmp_path / "ob").exists()


class _SolPool:
    def __init__(self, sols: dict[str, dict]) -> None:
        self.sols = sols
        self.fetched: list[str] = []

    def solutions(self, *, token):  # noqa: ARG002
        return {r: {"session_id": s["session_id"], "at": s["updated"]} for r, s in self.sols.items()}

    def solution(self, ref, *, token):  # noqa: ARG002
        self.fetched.append(ref)
        return self.sols[ref]


@pytest.mark.tier1
def test_sync_pulls_missing_solutions_and_marks(tmp_path):
    rec = {"ref": "ns/a:1", "session_id": "s1", "updated": 5.0, "final": "passed",
           "entries": [_cmd(0)]}
    pool = _SolPool({"ns/a:1": rec})
    marked: list[str] = []
    assert sync_solutions(tmp_path, pool, "t", marked.append) == 1
    assert load_solution(tmp_path, "ns/a:1")["entries"][0]["output"] == "o0\n"
    assert marked == ["ns/a:1"]
    assert sync_solutions(tmp_path, pool, "t") == 0          # already here: no refetch
    assert pool.fetched == ["ns/a:1"]


@pytest.mark.tier1
def test_save_and_load_solution(tmp_path):
    save_solution(tmp_path, "x/y:2", {"session_id": "s"})
    assert load_solution(tmp_path, "x/y:2") == {"session_id": "s"}
    assert load_solution(tmp_path, "nope:1") is None


@pytest.mark.tier1
def test_solution_text_and_cli(tmp_path, monkeypatch):
    from hashpass import cli  # noqa: PLC0415
    monkeypatch.delenv("HASHPASS_POOL", raising=False)
    env = cli.Home(tmp_path)
    rec = {"ref": "ns/a:1", "updated": 0.0, "entries": [_cmd(0), {"command": "true", "output": ""}]}
    text = solution_text(rec, ansi=False)
    assert text.splitlines()[0].startswith("ns/a:1  ·  зачтено ")
    assert "$ c0\no0\n$ true\n" in text
    out: list[str] = []
    io_ = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "T")
    assert cli.cmd_solution(env, "ns/a:1", io_) == 1
    assert cli.NO_SOLUTION in out[-1]
    save_solution(tmp_path, "ns/a:1", rec)
    assert cli.cmd_solution(env, "ns/a:1", io_) == 0
    assert "$ c0" in out[-1]
