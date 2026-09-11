"""
Extract reference commands from a task's Taskfile (attachment), for anti-bot flags.

A task's "reference" is whatever the author wrote as `solve` -- both the newer DSL
(`solve:` block with indented commands) and the older `task.toml` (`commands = [...]`
per `[[stage]]`) are supported. Commands are normalised so the comparison used by
`render_history` is stable against extra whitespace but nothing more (a teacher-shown
flag, not a rule).
"""
import contextlib
import re
import tomllib

_SOLVE_HEADER = re.compile(r"^([ \t]*)solve\s*:\s*$")
_WORDS = re.compile(r"\s+")


def _dsl_solves(text: str) -> list[str]:
    """Parse Taskfile DSL: every indented line under each `solve:` header is one command."""
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        header = _SOLVE_HEADER.match(lines[i])
        if header is None:
            i += 1
            continue
        base = header.group(1)
        i += 1
        while i < len(lines):
            line = lines[i]
            if not line.strip():                 # blank line inside a block: keep scanning
                i += 1
                continue
            leading = line[: len(line) - len(line.lstrip())]
            if len(leading) <= len(base):        # dedent (or same indent): block ended
                break
            out.append(line.strip())
            i += 1
    return out


def _toml_commands(text: str) -> list[str]:
    """Parse task.toml: every stage's `commands = [...]` (older TOML format)."""
    with contextlib.suppress(tomllib.TOMLDecodeError, ValueError):
        data = tomllib.loads(text)
        return [cmd.strip()
                for stage in data.get("stage", []) if isinstance(stage, dict)
                for cmd in stage.get("commands", []) or () if isinstance(cmd, str)]
    return []


def normalise(cmd: str) -> str:
    """Compress the runs of whitespace so `sort  a` and `sort a` compare equal."""
    return _WORDS.sub(" ", cmd.strip())


def reference_commands(taskfile_text: str) -> list[str]:
    """Extract every reference command from a Taskfile (DSL and/or task.toml), normalised."""
    if not taskfile_text:
        return []
    raw = _toml_commands(taskfile_text) + _dsl_solves(taskfile_text)
    return [normalise(c) for c in raw if c.strip()]
