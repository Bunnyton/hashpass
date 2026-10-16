"""Tier2: /attempt streaming, /submit closing a session, /solutions + /solution isolation."""
# ruff: noqa: PLR2004
import urllib.error
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest
from tests.registry.test_submit import _publish

SID = "b" * 32


def _e(cmd: str, out: str) -> dict:
    return {"command": cmd, "output": out, "ts": "t", "typing": 2.0, "pasted": False}


@pytest.mark.tier2
def test_attempt_stream_submit_and_solution(registry, tmp_path):
    td, _ = _publish(registry, tmp_path)
    sc = RemoteRegistry(registry.base_url)
    tok = sc.register("stud", "pass123!", group="G")
    assert sc.attempt("lab:1", SID, 0, [_e("lss", "lss: not found\n")], token=tok) == {"length": 1}
    with pytest.raises(urllib.error.HTTPError) as err:
        sc.attempt("lab:1", SID, 0, [_e("ls", "")], token=tok)
    assert err.value.code == HTTPStatus.CONFLICT
    assert sc.attempt("lab:1", SID, 1, [_e("ls", "a b\n")], token=tok)["length"] == 2
    assert sc.solutions(token=tok) == {}
    res = sc.submit("lab:1", task_digest(td), passed=True, session_id=SID, token=tok)
    assert res["status"] == "passed"
    assert set(sc.solutions(token=tok)) == {"lab:1"}
    sol = sc.solution("lab:1", token=tok)
    assert [(e["command"], e["output"]) for e in sol["entries"]] == [
        ("lss", "lss: not found\n"), ("ls", "a b\n")]
    assert sol["final"] == "passed"


@pytest.mark.tier2
def test_solution_is_private_to_student(registry, tmp_path):
    td, atok = _publish(registry, tmp_path)
    a = RemoteRegistry(registry.base_url)
    tok_a = a.register("stud", "pass123!", group="G")
    a.attempt("lab:1", SID, 0, [_e("ls", "x\n")], token=tok_a)
    a.submit("lab:1", task_digest(td), passed=True, session_id=SID, token=tok_a)
    b = RemoteRegistry(registry.base_url)
    tok_b = b.register("other", "pass123!", group="G")
    with pytest.raises(urllib.error.HTTPError) as err:
        b.solution("lab:1", user="stud", token=tok_b)
    assert err.value.code == HTTPStatus.FORBIDDEN
    with pytest.raises(urllib.error.HTTPError) as err:
        b.solution("lab:1", token=tok_b)
    assert err.value.code == HTTPStatus.NOT_FOUND
    # the teacher (admin) may read any student's solution
    assert RemoteRegistry(registry.base_url).solution("lab:1", user="stud", token=atok)["entries"]


@pytest.mark.tier2
def test_attempt_unknown_ref_and_bad_session(registry, tmp_path):
    _publish(registry, tmp_path)
    sc = RemoteRegistry(registry.base_url)
    tok = sc.register("stud", "pass123!", group="G")
    with pytest.raises(urllib.error.HTTPError) as err:
        sc.attempt("nope:1", SID, 0, [], token=tok)
    assert err.value.code == HTTPStatus.NOT_FOUND
    with pytest.raises(urllib.error.HTTPError) as err:
        sc.attempt("lab:1", "../x", 0, [], token=tok)
    assert err.value.code == HTTPStatus.BAD_REQUEST


@pytest.mark.tier2
def test_teacher_sees_attempts_with_output_on_the_site(registry, tmp_path):
    from tests.registry.test_images_web import _author_cookie, _req  # noqa: PLC0415
    _publish(registry, tmp_path)
    sc = RemoteRegistry(registry.base_url)
    tok = sc.register("stud", "pass123!", group="G")
    sc.attempt("lab:1", SID, 0, [_e("cat nofile", "cat: nofile: No such file or directory\n")],
               token=tok)
    opener, cookie = _author_cookie(registry)
    _, _, matrix = _req(opener, "GET", f"{registry.base_url}/web", cookie=cookie)
    assert "◐" in matrix
    _, _, body = _req(opener, "GET", f"{registry.base_url}/web/history?user=stud&ref=lab%3A1",
                      cookie=cookie)
    assert "cat: nofile: No such file or directory" in body
    assert "сейчас решает" in body


@pytest.mark.tier2
def test_a_passed_task_is_not_processed_again(registry, tmp_path):
    td, _ = _publish(registry, tmp_path)
    sc = RemoteRegistry(registry.base_url)
    tok = sc.register("stud", "pass123!", group="G")
    sc.attempt("lab:1", SID, 0, [_e("whoami", "stud\n")], token=tok)
    first = sc.submit("lab:1", task_digest(td), passed=True, session_id=SID, token=tok)
    before = sc.progress(token=tok)["stud"]["lab:1"]
    again = "c" * 32
    # a re-run of a credited task: the pool neither stores its commands nor a second solution
    assert sc.attempt("lab:1", again, 0, [_e("ls", "x\n")], token=tok)["ignored"] is True
    second = sc.submit("lab:1", task_digest(td), passed=True, session_id=again, token=tok)
    assert second == first
    assert sc.progress(token=tok)["stud"]["lab:1"] == before
    assert sc.solution("lab:1", token=tok)["session_id"] == SID
    assert sc.solutions(token=tok)["lab:1"]["session_id"] == SID
    # a digest-mismatch after the credit does not take it back either
    sc.submit("lab:1", "other-digest", passed=True, token=tok)
    assert sc.progress(token=tok)["stud"]["lab:1"]["status"] == "passed"
