import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.tier1
def test_shell_captures_last_cmd_and_output(tmp_path):
    root = tmp_path
    (root / ".hash").mkdir()
    shell = Path("src/hashpass/runtime/usr/bin/hash").read_text(encoding="utf-8")
    (root / "hash").write_text(shell, encoding="utf-8")
    (root / "hash").chmod(0o755)
    # прогоняем shell, скармливая команды на stdin
    subprocess.run(
        [sys.executable, str(root / "hash")],
        cwd=root,
        input="echo hi\nexit\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert (root / ".hash/.cmd").read_text(encoding="utf-8").strip() == "echo hi"
    assert (root / ".hash/.cmd.out").read_text(encoding="utf-8").strip() == "hi"


@pytest.mark.tier1
def test_shell_captures_last_cmd_and_transcript_log(tmp_path):
    root = tmp_path
    (root / ".hash").mkdir()
    shell = Path("src/hashpass/runtime/usr/bin/hash").read_text(encoding="utf-8")
    (root / "hash").write_text(shell, encoding="utf-8")
    (root / "hash").chmod(0o755)
    subprocess.run(
        [sys.executable, str(root / "hash")],
        cwd=root,
        input="echo hi\necho bye\nexit\n",
        capture_output=True,
        text=True,
        check=False,
    )
    # back-compat: .cmd / .cmd.out reflect the LAST command
    assert (root / ".hash/.cmd").read_text(encoding="utf-8").strip() == "echo bye"
    assert (root / ".hash/.cmd.out").read_text(encoding="utf-8").strip() == "bye"
    # NEW: the transcript log accumulates ALL commands + their outputs
    log = (root / ".hash/.cmd.log").read_text(encoding="utf-8")
    assert "echo hi" in log
    assert "echo bye" in log
    assert "hi" in log
    assert "bye" in log
    assert log.endswith("\n")   # each record is newline-terminated; no glued-on next "$ " line
