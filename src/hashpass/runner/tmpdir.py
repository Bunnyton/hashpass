import shutil
import subprocess
from pathlib import Path

from .base import RunResult


class TmpdirRunner:
    """Run commands in a temporary directory without isolation."""

    def __init__(self, workdir: Path) -> None:
        """
        Initialize with a work directory.

        Args:
            workdir: Path to the work directory.

        """
        self._root = Path(workdir) / "rootfs"

    def prepare(self, lowers: list[Path]) -> None:
        """
        Prepare the rootfs by copying lower directories.

        Args:
            lowers: List of directories to copy into rootfs.

        """
        self._root.mkdir(parents=True, exist_ok=True)
        for low in lowers:
            shutil.copytree(low, self._root, dirs_exist_ok=True)

    def run(self, argv: list[str]) -> RunResult:
        """
        Run a command in the rootfs.

        Args:
            argv: Command and arguments to run.

        Returns:
            RunResult with stdout, stderr, and exit code.

        """
        p = subprocess.run(  # noqa: S603
            argv,
            cwd=self._root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return RunResult(p.stdout, p.stderr, p.returncode)

    @property
    def rootfs(self) -> Path:
        """Root filesystem path."""
        return self._root

    def teardown(self) -> None:
        """Clean up the rootfs directory."""
        shutil.rmtree(self._root, ignore_errors=True)
