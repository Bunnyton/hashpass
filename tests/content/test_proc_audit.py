"""
Tier3 validation of the Phase-5 sample task `proc-audit`: a real apt install + process search.

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
    "apt-get update >/dev/null 2>&1\n"
    "apt-get install -y procps >/dev/null 2>&1\n"
    "dpkg -s procps | grep '^Status:' > /install-status.txt"
)
_AUDIT = "sleep 600 &\nsleep 0.3\npgrep -x sleep | wc -l > /proc-count.txt"


@pytest.mark.tier3
def test_proc_audit_discriminates_both_stages(tmp_path, base_tar):
    recipe = load_recipe(_TASKFILE)
    store = ImageStore(tmp_path / "images")
    build_task(recipe, store, base_tar=base_tar, workdir=tmp_path / "bt", passes=2)

    session = run_task("proc-audit:1", store, tmp_path / "run",
                       base_tar=base_tar, student_id="s1", nonce="n1")
    try:
        # Stage 1 (apt install): a bogus status is rejected; the real install advances + mints a key.
        assert session.feed("echo nope > /install-status.txt", ts=_TS).advanced is False
        r1 = session.feed(_INSTALL, ts=_TS)
        assert r1.advanced is True
        assert r1.local_key is not None

        # Stage 2 (process search): a wrong count is rejected; the real pgrep audit advances.
        assert session.feed("echo 0 > /proc-count.txt", ts=_TS).advanced is False
        r2 = session.feed(_AUDIT, ts=_TS)
        assert r2.advanced is True
        assert r2.local_key is not None
    finally:
        session.teardown()
