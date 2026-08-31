import pytest

from hashpass.hidden import stage_hidden_layer


@pytest.mark.tier1
def test_stage_hidden_layer_builds_tree_and_copies(tmp_path):
    work_src = tmp_path / "author_hidden"
    (work_src / "sub").mkdir(parents=True)
    (work_src / "verify.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (work_src / "sub" / "art.txt").write_text("hi", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "checks.json").write_text('{"task_id":"t","stages":[]}', encoding="utf-8")

    hp = stage_hidden_layer(tmp_path / "hp", work_src=work_src, bundle_dir=bundle)

    assert (hp / "bin").is_dir()
    assert (hp / "task").is_dir()
    assert (hp / "work").is_dir()
    assert (hp / "state.json").read_text(encoding="utf-8") == "{}"
    assert (hp / "history").read_text(encoding="utf-8") == ""
    assert (hp / "work" / "verify.sh").read_text(encoding="utf-8") == "#!/bin/sh\necho ok\n"
    assert (hp / "work" / "sub" / "art.txt").read_text(encoding="utf-8") == "hi"
    assert (hp / "task" / "checks.json").exists()


@pytest.mark.tier1
def test_stage_hidden_layer_bare_layout(tmp_path):
    hp = stage_hidden_layer(tmp_path / "hp")
    assert list((hp / "work").iterdir()) == []
    assert (hp / "state.json").read_text(encoding="utf-8") == "{}"
