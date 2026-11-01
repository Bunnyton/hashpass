"""
Tier1: a background boot never reads the student's terminal (spec 2026-11-02).

A lab node booted with the terminal as stdin ran nspawn's interactive console on it and took the
keys typed into the student's console: `curl` was typed and never ran (found live 2026-11-02).
"""
import subprocess

import pytest

from hashpass.runner import nspawn
from hashpass.runner.nspawn import NspawnRunner


@pytest.mark.tier1
def test_boot_detaches_from_the_terminal(tmp_path, monkeypatch):
    seen: dict = {}

    class FakePopen:
        def __init__(self, argv: list[str], **kw: object) -> None:
            seen["argv"], seen["kw"] = argv, kw

    monkeypatch.setattr(nspawn.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(nspawn.subprocess, "run",
                        lambda *_a, **_k: subprocess.CompletedProcess([], 0, b"", b""))
    NspawnRunner(tmp_path).boot("hp-1-aaaaaaaa", ["--hostname=web"])
    assert seen["kw"]["stdin"] is subprocess.DEVNULL
    assert "--console=passive" in seen["argv"]
    assert seen["argv"].index("--hostname=web") < seen["argv"].index("-D")
