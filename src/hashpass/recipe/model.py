"""Image/task recipe model: parsed Imagefile/Taskfile as frozen dataclasses."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CopyStep:
    """A `copy <src> <dst>` build step: host source and in-image destination."""

    src: str
    dst: str


@dataclass(frozen=True)
class RunStep:
    """A `run <command>` build step."""

    cmd: str


@dataclass(frozen=True)
class ExecAction:
    """An `exec <file-or-command>` action: run a hidden-layer script or shell command (§6)."""

    value: str


@dataclass(frozen=True)
class SayAction:
    """A `say [dramatic] "<text>"` action: render literal text (optionally with dramatic pacing)."""

    text: str
    dramatic: bool = False


@dataclass(frozen=True)
class ShowFileAction:
    """A `show file <path>` action: render a file's contents (large -> pager)."""

    path: str


@dataclass(frozen=True)
class ReadAction:
    """A `read <file>` action: render a Markdown file as paged, streamed narrative (§7)."""

    path: str


Action = ExecAction | SayAction | ShowFileAction | ReadAction


@dataclass(frozen=True)
class TriesCond:
    """`tries N`: fires after N real (neutral-excluded) attempts on the stage."""

    n: int


@dataclass(frozen=True)
class IdleCond:
    """`idle N`: fires after N seconds without progress."""

    seconds: float


@dataclass(frozen=True)
class CmdCond:
    """`cmd <base> [has <f...>] [missing <f...>]`: fires on a matching student command."""

    base: str
    has: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputCond:
    """`output "<substr>"`: fires when the last output contained the substring."""

    substr: str


Condition = TriesCond | IdleCond | CmdCond | OutputCond


@dataclass(frozen=True)
class HintRule:
    """One `hint <condition> <action>` rule (first-match-wins in source order, §7.1)."""

    condition: Condition
    action: Action


@dataclass(frozen=True)
class Voice:
    """Session voice: `hello` actions fired on first enter, `bye` actions on all-passed (§7.2)."""

    hello: tuple[Action, ...] = ()
    bye: tuple[Action, ...] = ()


@dataclass(frozen=True)
class Settings:
    """Render settings (§7.2): `type-mode`, `type-speed` chars/sec, `pager` for large `show file`."""

    type_mode: str = "normal"
    type_speed: int = 45
    user: str = "student"   # console login user for `run` (non-root by default; `root` for privileged tasks)
    sudo: bool = True       # whether that user is a (classic, password) sudoer in the container
    pager: bool = False
    similarity: int = 90    # percent (0-100): min output similarity to accept an `observe output` stage


@dataclass(frozen=True)
class StageSpec:
    """One `stage` block: reference solution, observed paths, delegated hooks, hint rules."""

    message: str
    solve: tuple[str, ...]
    observe: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    neutral: tuple[str, ...] = ()
    check: ExecAction | None = None
    on_enter: tuple[Action, ...] = ()
    on_pass: tuple[Action, ...] = ()
    hints: tuple[HintRule, ...] = ()
    accept_cmds: tuple[str, ...] = ()   # `accept cmd "<substr>"`: a command that passes the stage
    match_output: bool = False          # `observe output`: grade on command stdout (fuzzy, `similarity`)


@dataclass(frozen=True)
class Recipe:
    """A parsed image/task recipe: self-name/version, parents, build steps, optional task logic."""

    name: str
    version: str
    parents: tuple[str, ...]
    steps: tuple[CopyStep | RunStep, ...]  # copy/run in SOURCE order
    stages: tuple[StageSpec, ...] = ()
    hidden: str | None = None
    readme: str | None = None
    voice: Voice = field(default_factory=Voice)
    settings: Settings = field(default_factory=Settings)
    react: tuple[Action, ...] = ()
    intro: tuple[Action, ...] = ()     # top-level actions before the first stage (session opener)
    outro: tuple[Action, ...] = ()     # top-level actions after the last stage (on all-passed)


def image_ref(r: Recipe) -> str:
    """Return the recipe's self-reference `name:version`."""
    return f"{r.name}:{r.version}"


def is_task(recipe: Recipe) -> bool:
    """Return True if the recipe carries task logic (has at least one stage)."""
    return bool(recipe.stages)
