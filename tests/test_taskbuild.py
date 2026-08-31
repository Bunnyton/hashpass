import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import build_task
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskstore import load_task

_DERIVED = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt

stage "count them"
  solve wc -l < /errors.txt > /count.txt
  observe /count.txt
"""


@pytest.mark.tier3
def test_build_task_derives_and_stores_artifacts(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    stored = build_task(parse_recipe(_DERIVED), store, base_tar=base_tar,
                        workdir=tmp_path / "bt", passes=2)
    # image built + stored
    assert store.exists("logtask:1")
    # bundle: two derived stages, each canonical carries a real signal
    assert (stored.bundle_dir / "checks.json").exists()
    checks = load_bundle(stored.bundle_dir).checks
    assert checks.task_id == "logtask"
    assert len(checks.stages) == 2  # noqa: PLR2004
    assert any(k != "<output>" for k in checks.stages[0].canonical)
    # hidden /hp staged with the bundle under task/
    assert (stored.hp_src_dir / "task" / "checks.json").exists()
    assert (stored.hp_src_dir / "state.json").read_text(encoding="utf-8") == "{}"
    # meta records derived acceptance for both stages
    meta = load_task("logtask:1", store).meta
    assert [s.acceptance for s in meta.stages] == ["derived", "derived"]
    assert meta.image_ref == "logtask:1"


@pytest.mark.tier1
def test_build_task_rejects_passes_below_two(tmp_path):
    store = ImageStore(tmp_path / "images")
    recipe = parse_recipe('image t:1\nstage "x"\n  solve echo hi\n  observe o\n')
    # guard fires before any build/nspawn, so the (absent) base_tar is never read
    with pytest.raises(ValueError, match="passes must be >= 2"):
        build_task(recipe, store, base_tar=tmp_path / "none.tar", workdir=tmp_path / "b", passes=1)
