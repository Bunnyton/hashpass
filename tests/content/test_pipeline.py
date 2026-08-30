"""Tier1: derive->bundle->PlaySession end-to-end on the authored sample tasks."""
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.play import PlaySession
from hashpass.progress import new_progress
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.bundle import Bundle, dump_bundle, load_bundle
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.model import TaskCode, load_task_code

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TS = "2026-08-30T12:00:00Z"

# task_id -> the observed file a wrong solution corrupts
OBSERVED = {"hello": "hello.txt", "list-files": "listing.txt", "grep-todo": "found.txt"}


def _factory(tmp_path: Path) -> Callable[[], TmpdirRunner]:
    """Return a factory of fresh, prepared TmpdirRunners under tmp_path."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


def _solve(task: TaskCode, tmp_path: Path, name: str,
           commands: list[str]) -> tuple[Path, str]:
    """
    Run setup + `commands` in one fresh runner; return its rootfs + the script's stdout.

    Caveat: this returns the WHOLE script's stdout, whereas derive's `run_stage`
    captures only the LAST command's stdout. Faithful only when the reference
    commands emit nothing to stdout (our three tasks redirect) — for output-based
    tasks validate `<output>` via `capture_candidate` (see test_codegen_path.py).
    """
    r = TmpdirRunner(tmp_path / name)
    r.prepare([])
    result = r.run(["sh", "-c", "\n".join([*task.setup, *commands])])
    return r.rootfs, result.stdout


@pytest.mark.tier1
@pytest.mark.parametrize("task_id", list(OBSERVED))
def test_pipeline_accepts_correct_rejects_wrong(task_id, tmp_path):
    """derive->bundle->play accepts the reference solve and rejects a wrong one."""
    task = load_task_code(CONTENT / task_id / "task.toml")
    derived = derive_checks(_factory(tmp_path / "derive"), task, passes=3)
    bundle_dir = tmp_path / "bundle"
    dump_bundle(Bundle(checks=derived, conditions={}, hints={}), bundle_dir)
    bundle = load_bundle(bundle_dir)

    # CORRECT: run the reference commands, feed the live rootfs + last stdout.
    good = PlaySession(bundle, new_progress(task.id, 1), student_id="alice", nonce="n1")
    rootfs, output = _solve(task, tmp_path, "good", list(task.stages[0].commands))
    ok = good.feed(command=task.stages[0].commands[-1], rootfs=rootfs,
                   last_output=output, ts=TS)
    assert ok.advanced
    assert ok.local_key is not None
    assert ok.local_key.startswith("key{")

    # WRONG: corrupt the observed file; a fresh session must not advance.
    bad = PlaySession(bundle, new_progress(task.id, 1), student_id="alice", nonce="n1")
    wrong_cmd = f"echo NOPE > {OBSERVED[task_id]}"
    rootfs_w, output_w = _solve(task, tmp_path, "wrong", [wrong_cmd])
    rejected = bad.feed(command=wrong_cmd, rootfs=rootfs_w, last_output=output_w, ts=TS)
    assert not rejected.advanced
    assert rejected.local_key is None
