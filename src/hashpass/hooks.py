"""Runtime hook engine: @command / @filter / @check registration + dispatch."""
from collections.abc import Callable


class HookRegistry:
    """Registry for runtime hooks: command, filter, and check dispatchers."""

    def __init__(self) -> None:
        """Initialize empty hook lists for command, filter, and check handlers."""
        self._command: list[dict] = []
        self._filter: list[dict] = []
        self._check: list[dict] = []

    def command(self, stages: list[int] | None = None) -> Callable:
        def register(handler: Callable) -> Callable:
            self._command.append({"stages": stages, "handler": handler})
            return handler
        return register

    def filter(self, stages: list[int] | None = None) -> Callable:
        def register(handler: Callable) -> Callable:
            self._filter.append({"stages": stages, "handler": handler})
            return handler
        return register

    def check(self, stages: list[int] | None = None) -> Callable:
        def register(handler: Callable) -> Callable:
            self._check.append({"stages": stages, "handler": handler})
            return handler
        return register

    @staticmethod
    def _applies(stages: list[int] | None, stage: int) -> bool:
        return stages is None or stage in stages

    def run_command(self, cmd: str, stage: int) -> dict:
        res: dict = {"before": [], "cmd": [cmd], "after": []}
        for ch in self._command:
            if self._applies(ch["stages"], stage) and res["cmd"]:
                r = ch["handler"](cmd, stage)
                res["before"].extend(r["before"])
                res["after"].extend(r["after"])
                res["cmd"] = r["cmd"]
        return res

    def run_filter(self, cmd: str, data: str, stage: int) -> str:
        for ch in self._filter:
            if self._applies(ch["stages"], stage):
                data = ch["handler"](cmd, data, stage)
        return data

    def run_check(self, cmd: str, stage: int) -> bool | None:
        for ch in self._check:
            if self._applies(ch["stages"], stage):
                res = ch["handler"](cmd, stage)
                if res is not None:
                    return res
        return None


registry = HookRegistry()
command = registry.command
filter = registry.filter  # noqa: A001
check = registry.check
