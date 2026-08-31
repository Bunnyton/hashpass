"""Line-based, indentation-aware parser for image/task recipes (Imagefile = Taskfile)."""
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.recipe.model import (
    Action,
    CmdCond,
    Condition,
    CopyStep,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    Recipe,
    RunStep,
    SayAction,
    Settings,
    ShowFileAction,
    StageSpec,
    TriesCond,
    Voice,
)

_COPY_ARGC = 2
_DEFAULT_VERSION = "latest"
_STAGE_EVENTS = ("enter", "pass")
_QUOTE_MIN = 2
_ACTION_VERBS = ("exec", "say", "show")
_TYPE_MODES = ("instant", "normal", "dramatic")


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
    hello: list[Action] = field(default_factory=list)
    bye: list[Action] = field(default_factory=list)
    react: list[Action] = field(default_factory=list)
    settings: Settings | None = None


@dataclass
class _StageAcc:
    """Mutable accumulator for one stage block."""

    message: str
    solve: list[str] = field(default_factory=list)
    observe: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)
    check: ExecAction | None = None
    on_enter: list[Action] = field(default_factory=list)
    on_pass: list[Action] = field(default_factory=list)
    hints: list[HintRule] = field(default_factory=list)


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


def _parse_say(rest: str) -> SayAction:
    """Parse a `say [dramatic] "<text>"` action body (`dramatic` marks a slow, paused reply)."""
    dramatic = False
    head, _, tail = rest.partition(" ")
    if head == "dramatic":
        if not tail.strip():
            msg = "say dramatic requires text"
            raise ValueError(msg)
        dramatic = True
        rest = tail.strip()
    if not rest:
        msg = "say requires text"
        raise ValueError(msg)
    return SayAction(text=_unquote(rest), dramatic=dramatic)


def _parse_exec(rest: str) -> ExecAction:
    """Parse the body of an `exec <file-or-command>` action."""
    if not rest:
        msg = "exec requires a file or command"
        raise ValueError(msg)
    return ExecAction(rest)


def _parse_action(value: str) -> Action:
    """Parse an action value into ExecAction/SayAction/ShowFileAction (explicit verbs, §3.0)."""
    verb, _, rest = value.partition(" ")
    rest = rest.strip()
    if verb == "exec":
        return _parse_exec(rest)
    if verb == "say":
        return _parse_say(rest)
    if verb == "show":
        kind, _, path = rest.partition(" ")
        if kind != "file" or not path.strip():
            msg = f"only 'show file <path>' is supported, got: {value!r}"
            raise ValueError(msg)
        return ShowFileAction(path.strip())
    msg = f"expected an 'exec'/'say'/'show file' action, got: {value!r}"
    raise ValueError(msg)


def _positive_int(tok: str, kind: str) -> int:
    try:
        n = int(tok)
    except ValueError as exc:
        msg = f"{kind} condition needs an integer, got {tok!r}"
        raise ValueError(msg) from exc
    if n < 0:
        msg = f"{kind} condition needs a non-negative integer, got {tok!r}"
        raise ValueError(msg)
    return n


def _take_quoted(rest: str) -> tuple[str, str]:
    """Take a leading `"..."` literal (or one bare token); return (value, remaining)."""
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end == -1:
            msg = "output condition: unterminated quoted substring"
            raise ValueError(msg)
        return rest[1:end], rest[end + 1:].strip()
    tok, _, tail = rest.partition(" ")
    return tok, tail.strip()


def _parse_cmd_cond(rest: str) -> tuple[CmdCond, str]:
    """Parse `<base> [has <f...>] [missing <f...>]` up to the action verb; return (cond, action)."""
    toks = rest.split()
    if not toks:
        msg = "cmd condition requires a base command"
        raise ValueError(msg)
    base = toks[0]
    has: list[str] = []
    missing: list[str] = []
    bucket: list[str] | None = None
    i = 1
    while i < len(toks) and toks[i] not in _ACTION_VERBS:
        tok = toks[i]
        if tok == "has":
            bucket = has
        elif tok == "missing":
            bucket = missing
        elif bucket is None:
            msg = f"cmd condition: expected 'has'/'missing' before flags, got {tok!r}"
            raise ValueError(msg)
        else:
            bucket.append(tok)
        i += 1
    if i >= len(toks):
        msg = "cmd condition: hint needs an action (exec/say/show)"
        raise ValueError(msg)
    return CmdCond(base, tuple(has), tuple(missing)), " ".join(toks[i:])


def _parse_condition(value: str) -> tuple[Condition, str]:
    """Parse one explicit hint condition atom; return (Condition, remaining-action-text)."""
    kind, _, rest = value.partition(" ")
    rest = rest.strip()
    if kind == "tries":
        tok, _, tail = rest.partition(" ")
        return TriesCond(_positive_int(tok, "tries")), tail.strip()
    if kind == "idle":
        tok, _, tail = rest.partition(" ")
        return IdleCond(float(_positive_int(tok, "idle"))), tail.strip()
    if kind == "output":
        substr, tail = _take_quoted(rest)
        return OutputCond(substr), tail
    if kind == "cmd":
        return _parse_cmd_cond(rest)
    msg = f"unknown hint condition: {kind!r} (expected tries/idle/cmd/output)"
    raise ValueError(msg)


def _parse_hint(value: str) -> HintRule:
    """Parse a `hint <condition> <action>` line into a HintRule."""
    condition, action_text = _parse_condition(value)
    if not action_text:
        msg = f"hint requires an action after the condition: {value!r}"
        raise ValueError(msg)
    return HintRule(condition=condition, action=_parse_action(action_text))


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
    if acc.hidden is not None:
        msg = "duplicate 'hidden' directive"
        raise ValueError(msg)
    fields = value.split()
    if len(fields) != 1:
        msg = f"hidden requires a single <src> directory: {value!r}"
        raise ValueError(msg)
    acc.hidden = fields[0]


def _do_readme(value: str, acc: _Acc) -> None:
    if acc.readme is not None:
        msg = "duplicate 'readme' directive"
        raise ValueError(msg)
    fields = value.split()
    if len(fields) != 1:
        msg = f"readme requires a single <file>: {value!r}"
        raise ValueError(msg)
    acc.readme = fields[0]


def _do_react(value: str, acc: _Acc) -> None:
    head = "on command "
    if not value.startswith(head):
        msg = f"react must be 'react on command <action>': {value!r}"
        raise ValueError(msg)
    acc.react.append(_parse_action(value[len(head):].strip()))


_TOP_HANDLERS = {
    "image": _do_image,
    "from": _do_from,
    "copy": _do_copy,
    "run": _do_run,
    "hidden": _do_hidden,
    "readme": _do_readme,
    "react": _do_react,
}


def _reject(keyword: str) -> None:
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
    """Apply an `on <event> <action>` stage directive (enter/pass; exec/say/show actions)."""
    event, _, action = value.partition(" ")
    if event not in _STAGE_EVENTS:
        msg = f"unknown stage event: {event!r} (expected enter/pass)"
        raise ValueError(msg)
    target = sacc.on_enter if event == "enter" else sacc.on_pass
    target.append(_parse_action(action.strip()))


def _apply_check(value: str, sacc: _StageAcc) -> None:
    if sacc.check is not None:
        msg = "duplicate 'check' directive"
        raise ValueError(msg)
    verb, _, rest = value.partition(" ")
    if verb != "exec":
        msg = f"check requires an 'exec' action, got: {value!r} (expected an 'exec' predicate)"
        raise ValueError(msg)
    sacc.check = _parse_exec(rest.strip())


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
        _apply_check(value, sacc)
    elif kw == "hint":
        sacc.hints.append(_parse_hint(value))
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
        hints=tuple(sacc.hints),
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
            if value:
                msg = f"'solve:' takes no inline content; put commands on indented lines: {value!r}"
                raise ValueError(msg)
            i = _consume_solve_block(lines, i + 1, indent, sacc)
        else:
            _apply_simple_directive(kw, value, sacc)
            i += 1
    return _finalize_stage(sacc), i


def _parse_voice_block(lines: list[tuple[int, str]], start: int,
                       acc: _Acc) -> int:
    """Parse a `voice` block of `hello`/`bye <action>` lines; return next top-index."""
    i = start
    while i < len(lines) and lines[i][0] > 0:
        _, content = lines[i]
        kw, value = _kw_value(content)
        if kw == "hello":
            acc.hello.append(_parse_action(value))
        elif kw == "bye":
            acc.bye.append(_parse_action(value))
        else:
            msg = f"unknown voice directive: {kw!r} (expected hello/bye)"
            raise ValueError(msg)
        i += 1
    return i


def _parse_settings_block(lines: list[tuple[int, str]], start: int,
                          acc: _Acc) -> int:
    """Parse a `settings` block (type-mode/type-speed/pager); return next top-index."""
    if acc.settings is not None:
        msg = "duplicate 'settings' block"
        raise ValueError(msg)
    mode = "normal"
    speed = 45
    pager = False
    i = start
    while i < len(lines) and lines[i][0] > 0:
        _, content = lines[i]
        kw, value = _kw_value(content)
        if kw == "type-mode":
            if value not in _TYPE_MODES:
                msg = f"type-mode must be one of {_TYPE_MODES}, got {value!r}"
                raise ValueError(msg)
            mode = value
        elif kw == "type-speed":
            speed = _positive_int(value.strip(), "type-speed")
        elif kw == "pager":
            pager = value.strip() == "on"
        else:
            msg = f"unknown settings directive: {kw!r} (type-mode/type-speed/pager)"
            raise ValueError(msg)
        i += 1
    acc.settings = Settings(type_mode=mode, type_speed=speed, pager=pager)
    return i


_BLOCK_PARSERS = {"voice": _parse_voice_block, "settings": _parse_settings_block}


def parse_recipe(text: str) -> Recipe:
    """
    Parse Imagefile/Taskfile text into a Recipe (image directives + task + interactivity).

    Top-level (column 0): `image <name>:<ver>` (required, once), `from`, `copy`, `run`,
    `hidden <src>`, `readme <file>`, `react on command <action>`, the `settings`/`voice`
    blocks, and `stage "<message>"` blocks. A stage body holds
    `solve`/`observe`/`exclude`/`neutral`/`check`/`on enter|pass`/`hint <cond> <action>`.
    Blank and full-line `#` lines are ignored; inline `#` is preserved. Unknown directives
    raise ValueError.

    Raises:
        ValueError: missing/duplicate `image`, malformed directive/condition/action, a stage
            without `solve`, an unexpected indent, or an unknown directive.

    """
    acc = _Acc()
    lines = _significant(text)
    i = 0
    while i < len(lines):
        indent, content = lines[i]
        if indent != 0:
            msg = f"unexpected indentation (no open block): {content!r}"
            raise ValueError(msg)
        kw, value = _kw_value(content)
        if kw == "stage":
            stage, i = _parse_stage_block(value, lines, i + 1)
            acc.stages.append(stage)
            continue
        block = _BLOCK_PARSERS.get(kw)
        if block is not None:
            i = block(lines, i + 1, acc)
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
    voice = Voice(hello=tuple(acc.hello), bye=tuple(acc.bye))
    return Recipe(acc.name, acc.version, tuple(acc.parents), tuple(acc.steps),
                  tuple(acc.stages), acc.hidden, acc.readme,
                  voice=voice, settings=acc.settings or Settings(), react=tuple(acc.react))


def load_recipe(path: Path) -> Recipe:
    """Read an Imagefile/Taskfile from disk and parse it (see `parse_recipe`)."""
    return parse_recipe(Path(path).read_text(encoding="utf-8"))
