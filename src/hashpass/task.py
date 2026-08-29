import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Task:
    """Represents a task loaded from a directory with task.toml and readme.txt."""

    id: str
    readme: str
    check: dict

    @classmethod
    def load(cls, d: Path) -> "Task":
        """
        Load a task from a directory.

        Reads:
        - task.toml: TOML file with 'id' and 'check' fields
        - readme.txt: Optional text description (trimmed)
        """
        d = Path(d)
        meta = tomllib.loads((d / "task.toml").read_text(encoding="utf-8"))
        readme = (
            (d / "readme.txt").read_text(encoding="utf-8").strip()
            if (d / "readme.txt").exists()
            else ""
        )
        return cls(id=meta["id"], readme=readme, check=meta["check"])
