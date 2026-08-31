import pytest

from hashpass.taskstore import (
    StageMeta,
    TaskMeta,
    load_meta,
    meta_from_dict,
    meta_to_dict,
    save_meta,
)


def _meta() -> TaskMeta:
    return TaskMeta(
        image_ref="log-archive:1",
        stages=(
            StageMeta(message="collect", neutral=("ls", "cd"), check=None,
                      on_enter=("seed.sh",), on_pass=("cheer.sh",), acceptance="derived"),
            StageMeta(message="verify", neutral=(), check="verify.sh",
                      on_enter=(), on_pass=(), acceptance="handler"),
        ),
        readme="readme.txt",
    )


@pytest.mark.tier1
def test_meta_dict_round_trip():
    meta = _meta()
    assert meta_from_dict(meta_to_dict(meta)) == meta


@pytest.mark.tier1
def test_meta_file_round_trip(tmp_path):
    meta = _meta()
    save_meta(meta, tmp_path / "task")
    assert load_meta(tmp_path / "task") == meta


@pytest.mark.tier1
def test_meta_missing_readme_defaults_none():
    m = meta_from_dict({"image_ref": "x:1", "stages": []})
    assert m.readme is None
    assert m.stages == ()
