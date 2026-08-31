import pytest

from hashpass.recipe.parse import parse_recipe
from hashpass.recipe.taskbridge import recipe_to_taskcode
from hashpass.taskcode.model import StageCode, TaskCode


@pytest.mark.tier1
def test_recipe_to_taskcode_projects_stages():
    text = (
        "image pipe:1\n"
        "run seed the env\n"
        'stage "one"\n'
        "  solve sort f > s\n"
        "  observe s\n"
        "  exclude .cache\n"
        'stage "two"\n'
        "  solve:\n"
        "    uniq s > u\n"
        "    wc -l < u > n\n"
        "  observe n\n"
    )
    task = recipe_to_taskcode(parse_recipe(text))
    assert task == TaskCode(
        id="pipe",
        setup=(),
        stages=(
            StageCode(commands=("sort f > s",), observe=("s",), exclude=(".cache",), message="one"),
            StageCode(commands=("uniq s > u", "wc -l < u > n"), observe=("n",), exclude=(), message="two"),
        ),
    )


@pytest.mark.tier1
def test_recipe_to_taskcode_rejects_plain_image():
    with pytest.raises(ValueError, match="no stages"):
        recipe_to_taskcode(parse_recipe("image solo:1\nrun echo hi\n"))
