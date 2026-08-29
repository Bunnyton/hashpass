from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class RunResult:
    """Result of running a command."""

    stdout: str
    stderr: str
    exit_code: int


@runtime_checkable
class Runner(Protocol):
    """Protocol for running commands in an isolated environment."""

    def prepare(self, lowers: list[Path]) -> None: ...

    def run(self, argv: list[str]) -> RunResult: ...

    @property
    def rootfs(self) -> Path: ...

    def teardown(self) -> None: ...
