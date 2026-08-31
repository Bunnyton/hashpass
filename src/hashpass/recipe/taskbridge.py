"""Bridge a parsed task Recipe onto the taskcode derivation model (TaskCode)."""
from hashpass.recipe.model import Recipe
from hashpass.taskcode.model import StageCode, TaskCode


def recipe_to_taskcode(recipe: Recipe) -> TaskCode:
    """
    Project a task Recipe onto TaskCode for derivation.

    `setup` is empty: the `run`/`copy` environment is baked into the image the task is
    built on, so `solve` commands run against that image directly. Each stage's `solve`
    becomes `StageCode.commands` in source order.

    Raises:
        ValueError: if the recipe declares no stages (it is a plain image, not a task).

    """
    if not recipe.stages:
        msg = f"recipe {recipe.name!r} has no stages; not a task"
        raise ValueError(msg)
    return TaskCode(
        id=recipe.name,
        setup=(),
        stages=tuple(
            StageCode(
                commands=s.solve,
                observe=s.observe,
                exclude=s.exclude,
                message=s.message,
            )
            for s in recipe.stages
        ),
    )
