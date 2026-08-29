import pytest
from pathlib import Path
from hashpass.task import Task
from hashpass.check import stub_check
from hashpass.key import local_key


@pytest.mark.tier1
def test_task_load_and_stub_check_and_key(tmp_path):
    (tmp_path/"readme.txt").write_text("do it", encoding="utf-8")
    (tmp_path/"task.toml").write_text(
        'id="demo"\n[check]\nkind="path_exists"\npath="done.txt"\n',
        encoding="utf-8")
    t = Task.load(tmp_path)
    assert t.readme == "do it" and t.check["kind"] == "path_exists"
    assert stub_check(tmp_path, t.check) is False
    (tmp_path/"done.txt").write_text("x", encoding="utf-8")
    assert stub_check(tmp_path, t.check) is True
    k1 = local_key("demo", 0, "n1"); k2 = local_key("demo", 0, "n1")
    assert k1 == k2 and k1.startswith("key{") and k1.endswith("}")
    assert local_key("demo", 0, "n2") != k1
