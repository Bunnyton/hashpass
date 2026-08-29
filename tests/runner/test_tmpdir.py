from hashpass.runner.tmpdir import TmpdirRunner


def test_run_captures_stdout_and_fs(tmp_path):
    r = TmpdirRunner(tmp_path)
    r.prepare([])
    res = r.run(["sh", "-c", "echo hello > f.txt; echo done"])
    assert res.exit_code == 0
    assert res.stdout.strip() == "done"
    assert (r.rootfs / "f.txt").read_text(encoding="utf-8").strip() == "hello"
    r.teardown()
