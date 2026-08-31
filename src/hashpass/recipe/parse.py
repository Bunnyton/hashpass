"""Line-based parser for phase-1 image recipes (Imagefile): image/from/copy/run only."""
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.recipe.model import CopyStep, Recipe

_RESERVED = ("stage", "voice", "hidden", "readme")
_COPY_ARGC = 2
_DEFAULT_VERSION = "latest"


@dataclass
class _Acc:
    """Mutable accumulator for directives parsed so far."""

    name: str | None = None
    version: str = _DEFAULT_VERSION
    parents: list[str] = field(default_factory=list)
    copies: list[CopyStep] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)


def _do_image(value: str, acc: _Acc) -> None:
    if acc.name is not None:
        msg = "duplicate 'image' directive"
        raise ValueError(msg)
    name, _, version = value.partition(":")
    acc.name = name
    acc.version = version or _DEFAULT_VERSION


def _do_from(value: str, acc: _Acc) -> None:
    acc.parents.extend(ref.strip() for ref in value.split(",") if ref.strip())


def _do_copy(value: str, acc: _Acc) -> None:
    fields = value.split()
    if len(fields) != _COPY_ARGC:
        msg = f"copy requires <src> <dst>: {value!r}"
        raise ValueError(msg)
    acc.copies.append(CopyStep(fields[0], fields[1]))


def _do_run(value: str, acc: _Acc) -> None:
    acc.runs.append(value)


_HANDLERS = {"image": _do_image, "from": _do_from, "copy": _do_copy, "run": _do_run}


def _reject(keyword: str) -> None:
    if keyword in _RESERVED:
        msg = f"directive {keyword!r} is reserved for a later phase (not supported in phase 1)"
        raise ValueError(msg)
    msg = f"unknown directive: {keyword!r}"
    raise ValueError(msg)


def parse_recipe(text: str) -> Recipe:
    """
    Parse Imagefile text into a Recipe (phase-1 image directives only).

    Recognizes `image <name>:<ver>` (required, once), `from <ref>[, <ref> ...]`
    (declaration order preserved across directives), `copy <src> <dst>`, and
    `run <command>`. Blank lines and full-line `#` comments are ignored; an
    inline `#` is left intact so `run` command strings stay verbatim. Reserved
    later-phase directives (stage/voice/hidden/readme) and any unknown
    directive raise ValueError.

    Args:
        text: The Imagefile contents.

    Returns:
        The parsed Recipe.

    Raises:
        ValueError: On a missing/duplicate `image`, a reserved directive, an
            unknown directive, or a malformed `copy`.

    """
    acc = _Acc()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        value = parts[1] if len(parts) > 1 else ""
        handler = _HANDLERS.get(parts[0])
        if handler is None:
            _reject(parts[0])
        else:
            handler(value, acc)
    if not acc.name:
        msg = "recipe is missing a required 'image <name>:<ver>' directive"
        raise ValueError(msg)
    return Recipe(acc.name, acc.version, tuple(acc.parents), tuple(acc.copies), tuple(acc.runs))


def load_recipe(path: Path) -> Recipe:
    """Read an Imagefile from disk and parse it (see `parse_recipe`)."""
    return parse_recipe(Path(path).read_text(encoding="utf-8"))
