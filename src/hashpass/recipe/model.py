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
class Recipe:
    """A parsed phase-1 image recipe: self-name/version, parents, ordered build steps."""

    name: str
    version: str
    parents: tuple[str, ...]
    steps: tuple[CopyStep | RunStep, ...]  # copy/run in SOURCE order


def image_ref(r: Recipe) -> str:
    """Return the recipe's self-reference `name:version`."""
    return f"{r.name}:{r.version}"
