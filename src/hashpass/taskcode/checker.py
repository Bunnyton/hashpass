"""Stage acceptance: canonical matching with an optional @check escape + advisory conditions."""
from hashpass.canon import Observation, matches
from hashpass.cmd import parse_cmds
from hashpass.hooks import HookRegistry
from hashpass.taskcode.derive import StageChecks


def check_stage(checks: StageChecks, candidate: Observation, *,
                hooks: HookRegistry | None = None, stage: int = 0,
                probe_cmd: str = "") -> bool:
    if hooks is not None:
        result = hooks.run_check(probe_cmd, stage)
        if result is not None:
            return result
    return matches(checks.canonical, candidate,
                   threshold=checks.threshold, mode=checks.mode, k=checks.k)


def check_conditions(conditions: dict, commands: list[str]) -> bool:
    parsed = [c for raw in commands for c in parse_cmds(raw)]
    deny = set(conditions.get("deny", []))
    if any(c.basecmd in deny for c in parsed):
        return False
    for flag in conditions.get("require_flags", []):
        if not any(c.has_flag(flag) for c in parsed):
            return False
    for token in conditions.get("mention", []):
        if not any(token == c.basecmd or token in c.args for c in parsed):
            return False
    return True
