import pytest

from hashpass.recipe.model import CopyStep, Recipe, image_ref
from hashpass.recipe.parse import load_recipe, parse_recipe

_RECIPE = """\
# a phase-1 image recipe

image log-archive:1
from  base, coreutils-lab:1
copy  assets/ /home/student/
run   mkdir -p /var/log/app
run   touch /var/log/app/app.log
"""


@pytest.mark.tier1
def test_parse_full_recipe():
    recipe = parse_recipe(_RECIPE)
    assert recipe == Recipe(
        name="log-archive",
        version="1",
        parents=("base", "coreutils-lab:1"),
        copies=(CopyStep("assets/", "/home/student/"),),
        runs=("mkdir -p /var/log/app", "touch /var/log/app/app.log"),
    )
    assert image_ref(recipe) == "log-archive:1"


@pytest.mark.tier1
def test_missing_image_raises():
    with pytest.raises(ValueError, match="missing a required 'image"):
        parse_recipe("run echo hi\n")


@pytest.mark.tier1
def test_reserved_stage_directive_raises():
    with pytest.raises(ValueError, match="phase 1"):
        parse_recipe('image t:1\nstage "do the thing"\n')


@pytest.mark.tier1
def test_unknown_directive_raises():
    with pytest.raises(ValueError, match="unknown directive"):
        parse_recipe("image t:1\nfrobnicate stuff\n")


@pytest.mark.tier1
def test_load_recipe_from_disk(tmp_path):
    path = tmp_path / "Imagefile"
    path.write_text("image solo:2\n", encoding="utf-8")
    recipe = load_recipe(path)
    assert recipe.name == "solo"
    assert recipe.version == "2"
    assert recipe.parents == ()
