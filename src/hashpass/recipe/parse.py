"""Line-based, indentation-aware parser for image/task recipes (Imagefile = Taskfile)."""
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.recipe.model import CopyStep, ExecAction, Recipe, RunStep, StageSpec

_RESERVED_PHASE3 = ("voice", "hint", "say", "show", "settings", "react")
_COPY_ARGC = 2
_DEFAULT_VERSION = "latest"
_EXEC_PREFIX = "exec "
_STAGE_EVENTS = ("enter", "pass")
_QUOTE_MIN = 2


@dataclass
class _Acc:
    """Mutable accumulator for top-level directives."""

    name: str | None = None
    version: str = _DEFAULT_VERSION
    parents: list[str] = field(default_factory=list)
    steps: list[CopyStep | RunStep] = field(default_factory=list)
    stages: list[StageSpec] = field(default_factory=list)
    hidden: str | None = None
    readme: str | None = None


@dataclass
class _StageAcc:
    """Mutable accumulator for one stage block."""

    message: str
    solve: list[str] = field(default_factory=list)
    observe: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)
    check: ExecAction | None = None
    on_enter: list[ExecAction] = field(default_factory=list)
    on_pass: list[ExecAction] = field(default_factory=list)


def _significant(text: str) -> list[tuple[int, str]]:
    """Return (indent, stripped-content) for each non-blank, non-comment line."""
    out: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        expanded = raw.expandtabs()
        indent = len(expanded) - len(expanded.lstrip(" "))
        out.append((indent, stripped))
    return out


def _kw_value(content: str) -> tuple[str, str]:
    parts = content.split(maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _unquote(value: str) -> str:
    if len(value) >= _QUOTE_MIN and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _parse_action(value: str) -> ExecAction:
    """Parse a `<verb> …` action value. Phase 2 supports only `exec <file-or-command>`."""
    if value.startswith(_EXEC_PREFIX):
        body = value[len(_EXEC_PREFIX):].strip()
        if not body:
            msg = "exec requires a file or command"
            raise ValueError(msg)
        return ExecAction(body)
    verb = value.split(maxsplit=1)[0] if value else ""
    if verb in _RESERVED_PHASE3:
        msg = f"action {verb!r} is reserved for a later phase (phase 3 interactivity)"
        raise ValueError(msg)
    msg = f"expected an 'exec …' action, got: {value!r}"
    raise ValueError(msg)


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
    acc.steps.append(CopyStep(fields[0], fields[1]))


def _do_run(value: str, acc: _Acc) -> None:
    acc.steps.append(RunStep(value))


def _do_hidden(value: str, acc: _Acc) -> None:
    fields = value.split()
    if len(fields) != 1:
        msg = f"hidden requires a single <src> directory: {value!r}"
        raise ValueError(msg)
    acc.hidden = fields[0]


def _do_readme(value: str, acc: _Acc) -> None:
    fields = value.split()
    if len(fields) != 1:
        msg = f"readme requires a single <file>: {value!r}"
        raise ValueError(msg)
    acc.readme = fields[0]


_TOP_HANDLERS = {
    "image": _do_image,
    "from": _do_from,
    "copy": _do_copy,
    "run": _do_run,
    "hidden": _do_hidden,
    "readme": _do_readme,
}


def _reject(keyword: str) -> None:
    if keyword in _RESERVED_PHASE3:
        msg = f"directive {keyword!r} is reserved for a later phase (phase 3 interactivity)"
        raise ValueError(msg)
    msg = f"unknown directive: {keyword!r}"
    raise ValueError(msg)


def _consume_solve_block(lines: list[tuple[int, str]], start: int, base_indent: int,
                         sacc: _StageAcc) -> int:
    """Append every line indented deeper than `base_indent` as a verbatim command; return next index."""
    i = start
    while i < len(lines) and lines[i][0] > base_indent:
        sacc.solve.append(lines[i][1])
        i += 1
    if not sacc.solve:
        msg = "empty 'solve:' block"
        raise ValueError(msg)
    return i


def _apply_on(value: str, sacc: _StageAcc) -> None:
    """Apply an `on <event> <action>` stage directive."""
    event, _, action = value.partition(" ")
    if event not in _STAGE_EVENTS:
        msg = f"unknown stage event: {event!r} (expected enter/pass)"
        raise ValueError(msg)
    target = sacc.on_enter if event == "enter" else sacc.on_pass
    target.append(_parse_action(action.strip()))


def _apply_simple_directive(kw: str, value: str, sacc: _StageAcc) -> None:
    """Apply one single-line stage sub-directive (everything but the `solve:` block)."""
    if kw == "solve":
        if not value:
            msg = "solve requires an inline command or a 'solve:' block"
            raise ValueError(msg)
        sacc.solve.append(value)
    elif kw == "observe":
        sacc.observe.extend(value.split())
    elif kw == "exclude":
        sacc.exclude.extend(value.split())
    elif kw == "neutral":
        sacc.neutral.extend(value.split())
    elif kw == "check":
        sacc.check = _parse_action(value)
    elif kw == "on":
        _apply_on(value, sacc)
    else:
        _reject(kw)


def _finalize_stage(sacc: _StageAcc) -> StageSpec:
    if not sacc.solve:
        msg = f"stage {sacc.message!r} has no 'solve' reference solution"
        raise ValueError(msg)
    return StageSpec(
        message=sacc.message,
        solve=tuple(sacc.solve),
        observe=tuple(sacc.observe),
        exclude=tuple(sacc.exclude),
        neutral=tuple(sacc.neutral),
        check=sacc.check,
        on_enter=tuple(sacc.on_enter),
        on_pass=tuple(sacc.on_pass),
    )


def _parse_stage_block(header_value: str, lines: list[tuple[int, str]],
                       start: int) -> tuple[StageSpec, int]:
    """Parse a `stage` header + its indented body; return (StageSpec, next-top-index)."""
    if not header_value:
        msg = "stage requires a message"
        raise ValueError(msg)
    sacc = _StageAcc(message=_unquote(header_value))
    i = start
    while i < len(lines) and lines[i][0] > 0:
        indent, content = lines[i]
        kw, value = _kw_value(content)
        if kw == "solve:":
            i = _consume_solve_block(lines, i + 1, indent, sacc)
        else:
            _apply_simple_directive(kw, value, sacc)
            i += 1
    return _finalize_stage(sacc), i


def parse_recipe(text: str) -> Recipe:
    """
    Parse Imagefile/Taskfile text into a Recipe (image directives + optional stage blocks).

    Top-level (column 0): `image <name>:<ver>` (required, once), `from`, `copy`, `run`,
    `hidden <src>`, `readme <file>`, and `stage "<message>"` (opens an indented block of
    `solve`/`observe`/`exclude`/`neutral`/`check`/`on enter`/`on pass`). A `solve:` line
    opens a verbatim command block (deeper-indented lines). Blank and full-line `#` lines
    are ignored; inline `#` is preserved. Phase-3 interactivity directives
    (voice/hint/say/show/settings/react) and unknown directives raise ValueError.

    Raises:
        ValueError: missing/duplicate `image`, malformed directive, a stage without
            `solve`, an unexpected indent, or a reserved/unknown directive.

    """
    acc = _Acc()
    lines = _significant(text)
    i = 0
    while i < len(lines):
        indent, content = lines[i]
        if indent != 0:
            msg = f"unexpected indentation (no open stage): {content!r}"
            raise ValueError(msg)
        kw, value = _kw_value(content)
        if kw == "stage":
            stage, i = _parse_stage_block(value, lines, i + 1)
            acc.stages.append(stage)
            continue
        handler = _TOP_HANDLERS.get(kw)
        if handler is None:
            _reject(kw)
        else:
            handler(value, acc)
        i += 1
    if not acc.name:
        msg = "recipe is missing a required 'image <name>:<ver>' directive"
        raise ValueError(msg)
    return Recipe(acc.name, acc.version, tuple(acc.parents), tuple(acc.steps),
                  tuple(acc.stages), acc.hidden, acc.readme)


def load_recipe(path: Path) -> Recipe:
    """Read an Imagefile/Taskfile from disk and parse it (see `parse_recipe`)."""
    return parse_recipe(Path(path).read_text(encoding="utf-8"))
