import pytest

from hashpass.play import play
from hashpass.runner.tmpdir import TmpdirRunner


@pytest.mark.tier1
def test_play_returns_key_on_pass(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "readme.txt").write_text("create done.txt", encoding="utf-8")
    (task / "task.toml").write_text(
        'id="demo"\n[check]\nkind="path_exists"\npath="done.txt"\n',
        encoding="utf-8",
    )
    r = TmpdirRunner(tmp_path / "run")
    r.prepare([task])
    assert play(r, task, nonce="n") is None  # ещё не решено
    r.run(["sh", "-c", "touch done.txt"])
    assert play(r, task, nonce="n").startswith("key{")
    r.teardown()
