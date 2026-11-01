"""
Tier3 validation of `proc-audit`: a real apt install, then the process tree with PIDs.

Proves the whole authoring pipeline on realistic content: build the task on a real image, derive
acceptance on the mounted chain, then run a student session where the correct multi-command
solution advances (minting a local key) and a wrong one does not — for BOTH stages.
"""
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import load_recipe
from hashpass.taskbuild import build_task
from hashpass.taskrun import run_task

_TASKFILE = Path(__file__).resolve().parents[2] / "content" / "tasks" / "proc-audit" / "Taskfile"
_TS = "2026-08-31T00:00:00"

_INSTALL = (
    "sudo apt-get update >/dev/null 2>&1\n"
    "sudo apt-get install -y psmisc >/dev/null 2>&1"
)


@pytest.mark.tier3
def test_proc_audit_discriminates_both_stages(tmp_path, base_tar, monkeypatch):
    monkeypatch.chdir(_TASKFILE.parent)        # `copy data/…` is relative to the task dir
    recipe = load_recipe(_TASKFILE)
    store = ImageStore(tmp_path / "images")
    build_task(recipe, store, base_tar=base_tar, workdir=tmp_path / "bt", passes=2)

    session = run_task("proc-audit:1", store, tmp_path / "run",
                       base_tar=base_tar, student_id="s1", nonce="n1")
    try:
        # Stage 1 (apt install): pstree is missing until psmisc is really installed.
        assert session.feed("touch /home/student/pstree", ts=_TS).advanced is False
        r1 = session.feed(_INSTALL, ts=_TS)
        assert r1.advanced is True
        assert r1.local_key is not None

        # Stage 2 (process tree): a tree without PIDs is not enough; `pstree -p` advances.
        assert session.feed("pstree", ts=_TS).advanced is False
        # feed() runs commands under `sh -c`, not in an interactive bash: start one, as the console does
        r2 = session.feed("bash -c 'pstree -p; true'", ts=_TS)   # '; true': no exec shortcut
        assert r2.advanced is True
        assert r2.local_key is not None
    finally:
        session.teardown()
