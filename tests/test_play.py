import pytest

from hashpass.canon import FileState, matches
from hashpass.play import FeedResult, PlaySession, capture_candidate
from hashpass.progress import StageStatus, new_progress
from hashpass.sync import LocalSyncClient
from hashpass.taskcode.bundle import Bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskcode.execute import OUTPUT_KEY

_SECRET = b"server-secret-XYZ"
_TS = "2026-08-30T12:00:00Z"


def _stage(canonical) -> StageChecks:
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


def _bundle(hints=None) -> Bundle:
    checks = DerivedChecks(task_id="demo", stages=(
        _stage({"result.txt": FileState("file", "answer")}),
    ))
    return Bundle(checks=checks, conditions={}, hints=hints or {})


@pytest.mark.tier1
def test_capture_candidate_reads_canonical_files_and_folds_output(tmp_path):
    (tmp_path / "result.txt").write_text("answer", encoding="utf-8")
    checks = _stage({"result.txt": FileState("file", "answer"),
                     OUTPUT_KEY: FileState("file", "")})
    candidate = capture_candidate(tmp_path, checks, "hello stdout")
    assert candidate["result.txt"] == FileState("file", "answer")
    assert candidate[OUTPUT_KEY] == FileState("file", "hello stdout")


@pytest.mark.tier1
def test_feed_advances_on_correct_state_and_issues_local_key(tmp_path):
    session = PlaySession(_bundle(), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("answer", encoding="utf-8")
    result = session.feed(command="echo answer > result.txt", rootfs=tmp_path,
                          last_output="answer", ts=_TS)
    assert isinstance(result, FeedResult)
    assert result.advanced is True
    assert result.stage == 0
    assert result.local_key is not None
    assert result.local_key.startswith("key{")
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL
    assert 0 in session.evidences


@pytest.mark.tier1
def test_feed_does_not_advance_on_wrong_state_and_bumps_stuck(tmp_path):
    session = PlaySession(_bundle(), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("WRONG", encoding="utf-8")
    result = session.feed(command="echo WRONG > result.txt", rootfs=tmp_path,
                          last_output="WRONG", ts=_TS)
    assert result.advanced is False
    assert result.local_key is None
    assert session.progress.statuses[0] is StageStatus.OPEN
    assert session.stuck.commands_since_progress == 1


@pytest.mark.tier1
def test_feed_fires_matching_hint(tmp_path):
    hints = {0: [{"trigger": {"command": "sudo"}, "message": "no sudo needed"}]}
    session = PlaySession(_bundle(hints), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("nope", encoding="utf-8")
    result = session.feed(command="sudo rm x", rootfs=tmp_path, last_output="", ts=_TS)
    assert result.advanced is False
    assert result.hint == "no sudo needed"


@pytest.mark.tier1
def test_feed_stuck_fires_by_elapsed_seconds(tmp_path):
    hints = {0: [{"trigger": {"stuck": True}, "message": "take a break"}]}
    session = PlaySession(_bundle(hints), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    # one wrong command far in the future (>120s after the first) -> stuck by SECONDS, not commands
    session.feed(command="ls", rootfs=tmp_path, last_output="", ts="2026-08-30T12:00:00Z")
    r = session.feed(command="ls", rootfs=tmp_path, last_output="", ts="2026-08-30T12:05:00Z")
    assert session.stuck.commands_since_progress == 2  # noqa: PLR2004 # well under the 5-command threshold
    assert r.hint == "take a break"                      # fired by the 300s elapsed instead


@pytest.mark.tier1
def test_reverify_upgrades_local_pass_to_global(tmp_path):
    session = PlaySession(_bundle(), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("answer", encoding="utf-8")
    session.feed(command="echo answer > result.txt", rootfs=tmp_path,
                 last_output="answer", ts=_TS)
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = session.reverify(sync)
    assert mismatches == []
    assert session.progress.statuses[0] is StageStatus.PASSED_GLOBAL


@pytest.mark.tier1
def test_capture_candidate_existence_key_matches_by_kind_only(tmp_path):
    # An existence/kind-only canonical key (text=None) -- what `observe bool` (or a binary) yields.
    checks = StageChecks(canonical={"opt/x": FileState("file", None)})
    (tmp_path / "opt").mkdir()
    (tmp_path / "opt" / "x").write_text("ANY CONTENT AT ALL", encoding="utf-8")
    cand = capture_candidate(tmp_path, checks, "")
    assert cand["opt/x"] == FileState("file", None)          # content dropped, not compared
    assert matches(checks.canonical, cand)                   # exists as a file -> matches
    (tmp_path / "opt" / "x").unlink()
    assert not matches(checks.canonical, capture_candidate(tmp_path, checks, ""))  # gone -> no match


@pytest.mark.tier1
def test_capture_candidate_bool_dir_key_matches_without_recursion(tmp_path):
    checks = StageChecks(canonical={"d": FileState("dir", None)})   # `observe bool /d`
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "junk").write_text("noise", encoding="utf-8")
    cand = capture_candidate(tmp_path, checks, "")
    assert cand["d"] == FileState("dir", None) and "d/junk" not in cand   # the dir, not its content
    assert matches(checks.canonical, cand)
