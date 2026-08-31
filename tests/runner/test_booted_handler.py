import pytest

from hashpass.image.base import build_base
from hashpass.runner.booted import BootedNspawnRunner


@pytest.mark.tier3
def test_handler_overlay_sees_student_files_and_hp_without_busy_conflict(tmp_path, base_tar):
    hp = tmp_path / "hp"
    hp.mkdir()
    (hp / "token.txt").write_text("SECRET", encoding="utf-8")
    base = build_base(tmp_path / "base", from_tar=base_tar)   # bootable base (systemd installed)
    r = BootedNspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        # The student (in the booted machine) creates a file.
        r.run(["sh", "-c", "echo hi > /student.txt"])
        # A /hp handler runs on a SEPARATE fresh overlay (no busy-conflict with the booted mnt),
        # and sees BOTH the student's live file (stacked booted upper) AND the bound /hp.
        res = r.run(
            ["sh", "-c", "cat /student.txt; cat /hp/token.txt; printf ':%s' \"$HP_TRIES\""],
            binds=[(str(hp), "/hp")],
            setenv={"HP_TRIES": "4"},
        )
        assert res.exit_code == 0
        assert res.stdout == "hi\nSECRET:4"
        # A predicate handler returns the real exit code (acceptance basis for `check` stages).
        assert r.run(["sh", "-c", "grep -q hi /student.txt"], binds=[(str(hp), "/hp")]).exit_code == 0
        assert r.run(["sh", "-c", "grep -q NOPE /student.txt"], binds=[(str(hp), "/hp")]).exit_code != 0
        # The booted machine still runs (the handler did not disturb it).
        assert "systemd" in r.run(["sh", "-c", "ps -p 1 -o comm="]).stdout
    finally:
        r.teardown()
