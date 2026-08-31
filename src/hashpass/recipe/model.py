"""Image/task recipe model: parsed Imagefile as frozen dataclasses (phase 1: images only)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CopyStep:
    """A `copy <src> <dst>` build step: host source and in-image destination."""

    src: str
    dst: str


@dataclass(frozen=True)
class RunStep:
    """A `run <command>` build step."""

    cmd: str


@dataclass(frozen=True)
class ExecAction:
    """A delegated action: run `value` as a hidden-layer script or shell command (auto-detected at run time)."""

    value: str


@dataclass(frozen=True)
class StageSpec:
    """One `stage` block: reference solution, observed paths, and delegated hooks."""

    message: str
    solve: tuple[str, ...]
    observe: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    neutral: tuple[str, ...] = ()
    check: ExecAction | None = None
    on_enter: tuple[ExecAction, ...] = ()
    on_pass: tuple[ExecAction, ...] = ()


@dataclass(frozen=True)
class Recipe:
    """A parsed image/task recipe: self-name/version, parents, ordered build steps, optional task logic."""

    name: str
    version: str
    parents: tuple[str, ...]
    steps: tuple[CopyStep | RunStep, ...]  # copy/run in SOURCE order
    stages: tuple[StageSpec, ...] = ()
    hidden: str | None = None
    readme: str | None = None


def image_ref(r: Recipe) -> str:
    """Return the recipe's self-reference `name:version`."""
    return f"{r.name}:{r.version}"


def is_task(recipe: Recipe) -> bool:
    """Return True if the recipe carries task logic (has at least one stage)."""
    return bool(recipe.stages)
