"""Tier1: a fork offered back (merge request), reviewed by the original's owner (spec §2.8)."""
from pathlib import Path

import pytest

from tests.registry.test_push_commit import _http, _Pool, _push_with_files


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Pool:
    p = _Pool(registry, tmp_path)
    p.push("bob/lab", "1", image="one", task="t1")
    _push_with_files(p, b"image bob/lab:1", b"# old readme")                  # bob/lab:1_v2
    _http("POST", f"{p.url}/revisions/eve/lab/fork", token=p.tok["eve"], body={"from": "bob/lab:1"})
    sid = p.begin("eve/lab", "1", user="eve")[1]["staging"]                  # eve improves her fork
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"# better readme\n"
        info = tarfile.TarInfo("README.md")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    p.put("source", "eve/lab", "1", sid, buf.getvalue(), user="eve")
    assert p.commit("eve/lab", "1", sid, user="eve")[1]["ref"] == "eve/lab:1_v2"
    return p


def _offer(pool: _Pool) -> dict:
    code, body = _http("POST", f"{pool.url}/revisions/bob/lab/merges", token=pool.tok["eve"],
                       body={"from": "eve/lab:1", "comment": "поправила README"})
    assert code == 201, body  # noqa: PLR2004
    return body


@pytest.mark.tier1
def test_offer_diff_and_merge(pool: _Pool) -> None:
    row = _offer(pool)
    assert (row["from"], row["to_tag"], row["state"]) == ("eve/lab:1_v2", "1", "open")
    diff = _http("GET", f"{pool.url}/revisions/bob/lab/merges/{row['id']}/diff", token=pool.tok["bob"])[1]
    assert [(f["path"], f["change"]) for f in diff["files"]] == [("README.md", "changed")]
    assert "+# better readme" in diff["files"][0]["diff"]
    assert _http("POST", f"{pool.url}/revisions/bob/lab/merges/{row['id']}", token=pool.tok["eve"],
                 body={"action": "merge"})[0] == 403  # noqa: PLR2004
    code, done = _http("POST", f"{pool.url}/revisions/bob/lab/merges/{row['id']}", token=pool.tok["bob"],
                       body={"action": "merge"})
    assert (code, done["state"], done["result"]) == (200, "merged", "bob/lab:1_v3")
    info = _http("GET", f"{pool.url}/revisions/bob/lab", token=pool.tok["bob"])[1]
    assert info["tags"]["1"][-1]["merged_from"] == "eve/lab:1_v2"


@pytest.mark.tier1
def test_one_open_request_per_fork_tag_and_withdraw(pool: _Pool) -> None:
    first, second = _offer(pool), _offer(pool)
    assert first["id"] == second["id"]
    assert _http("POST", f"{pool.url}/revisions/bob/lab/merges/{first['id']}", token=pool.tok["eve"],
                 body={"action": "withdraw"})[1]["state"] == "withdrawn"


@pytest.mark.tier1
def test_only_a_fork_may_offer(pool: _Pool) -> None:
    pool.push("eve/other", "1", image="x", user="eve")
    code, body = _http("POST", f"{pool.url}/revisions/bob/lab/merges", token=pool.tok["eve"],
                       body={"from": "eve/other:1"})
    assert code == 400 and "не форк" in body["error"]  # noqa: PLR2004


@pytest.mark.tier1
def test_reject_with_a_reason(pool: _Pool) -> None:
    row = _offer(pool)
    done = _http("POST", f"{pool.url}/revisions/bob/lab/merges/{row['id']}", token=pool.tok["bob"],
                 body={"action": "reject", "reason": "не то"})[1]
    assert (done["state"], done["reason"]) == ("rejected", "не то")
    assert [r["state"] for r in _http("GET", f"{pool.url}/revisions/bob/lab/merges",
                                      token=pool.tok["eve"])[1]["merges"]] == ["rejected"]
