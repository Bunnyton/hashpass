"""Task-as-code model: TaskCode/StageCode dataclasses + TOML (de)serialization."""
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StageCode:
    """One stage: reference-solution commands + curated observed paths."""

    commands: tuple[str, ...]
    observe: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class TaskCode:
    """A whole task: id, seeded setup commands, and ordered stages."""

    id: str
    setup: tuple[str, ...]
    stages: tuple[StageCode, ...]


def toml_quote(s: str) -> str:
    """Escape string for TOML basic-string literal."""
    esc = (s.replace("\\", "\\\\").replace('"', '\\"')
           .replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r"))
    return f'"{esc}"'


def toml_list(items: tuple[str, ...]) -> str:
    """Serialize tuple of strings as TOML array-of-strings."""
    return "[" + ", ".join(toml_quote(x) for x in items) + "]"


def dump_task_code(task: TaskCode, path: Path) -> None:
    """Serialize TaskCode to TOML file."""
    lines = [f"id = {toml_quote(task.id)}", f"setup = {toml_list(task.setup)}"]
    for stage in task.stages:
        lines.append("")
        lines.append("[[stage]]")
        lines.append(f"commands = {toml_list(stage.commands)}")
        lines.append(f"observe = {toml_list(stage.observe)}")
        lines.append(f"exclude = {toml_list(stage.exclude)}")
        lines.append(f"message = {toml_quote(stage.message)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_task_code(path: Path) -> TaskCode:
    """Parse TaskCode from TOML file."""
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    stages = tuple(
        StageCode(
            commands=tuple(s.get("commands", [])),
            observe=tuple(s.get("observe", [])),
            exclude=tuple(s.get("exclude", [])),
            message=s.get("message", ""),
        )
        for s in data.get("stage", [])
    )
    return TaskCode(id=data["id"], setup=tuple(data.get("setup", [])), stages=stages)
