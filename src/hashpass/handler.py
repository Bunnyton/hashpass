"""HP_* handler contract (§6): build a delegated exec invocation and run it under /hp."""
import shlex
from dataclasses import dataclass
from pathlib import Path

from hashpass.recipe.model import ExecAction
from hashpass.runner.nspawn import NspawnRunner

_HP_WORK = "/hp/work"
_HP_STATE = "/hp/state.json"
_HP_HISTORY = "/hp/history"
_HP_ROOTFS = "/"


@dataclass(frozen=True)
class HandlerContext:
    """Inputs to one handler invocation (the HP_* channel, §6)."""

    student_cmd: str
    tries: int
    last_out: str
    stage: int


@dataclass(frozen=True)
class HandlerResult:
    """A handler's output: stdout (text directives) + exit code (predicate directives)."""

    stdout: str
    exit_code: int


def _split_args(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split a file handler's trailing tokens into positional argv and HP_ARG_* pairs."""
    positional: list[str] = []
    hp_args: dict[str, str] = {}
    for tok in tokens:
        key, sep, val = tok.partition("=")
        if sep and key and " " not in key:
            hp_args[key] = val
        else:
            positional.append(tok)
    return positional, hp_args


def build_invocation(action: ExecAction, ctx: HandlerContext, *,
                     hp_work_host: Path) -> tuple[list[str], dict[str, str]]:
    """
    Build (argv, setenv) for an `exec` handler, auto-detecting file vs shell command.

    File handler: first shlex token names a file under the hidden work dir
    (`hp_work_host/<tok>`) -> run `/hp/work/<tok> <student_cmd> [positional...]`;
    trailing `k=v` tokens become HP_ARG_k. Otherwise the whole value runs as
    `sh -c <value>`. Either way the full HP_* env is set.

    Args:
        action: The `exec` action whose value is the file-or-command.
        ctx: The current handler context (student command, tries, last output, stage).
        hp_work_host: Host path of `/hp/work` (used to detect a file handler).

    Returns:
        (argv, setenv) ready for `NspawnRunner.run(argv, setenv=setenv, ...)`.

    Raises:
        ValueError: if the action value is empty.

    """
    tokens = shlex.split(action.value)
    if not tokens:
        msg = "empty exec action"
        raise ValueError(msg)
    first = tokens[0]
    hp_args: dict[str, str] = {}
    if (hp_work_host / first).is_file():
        positional, hp_args = _split_args(tokens[1:])
        argv = [f"{_HP_WORK}/{first}", ctx.student_cmd, *positional]
    else:
        argv = ["sh", "-c", action.value]
    env = {
        "HP_TRIES": str(ctx.tries),
        "HP_LAST_OUT": ctx.last_out,
        "HP_HISTORY": _HP_HISTORY,
        "HP_STATE": _HP_STATE,
        "HP_ROOTFS": _HP_ROOTFS,
        "HP_STAGE": str(ctx.stage),
    }
    for key, val in hp_args.items():
        env[f"HP_ARG_{key}"] = val
    return argv, env


def run_handler(runner: NspawnRunner, action: ExecAction, ctx: HandlerContext, *,
                hp_dir: Path) -> HandlerResult:
    """
    Run one `exec` handler in a fresh mount-ns with `/hp` bound and HP_* set.

    Binds the host `hp_dir` at `/hp` for this single invocation only (a plain student
    run gets its own ns without `/hp`), then returns the handler's stdout + exit code.

    Args:
        runner: The prepared student NspawnRunner (its overlay is the student rootfs).
        action: The delegated `exec` action to run.
        ctx: The handler context (HP_* inputs).
        hp_dir: Host `/hp` tree to bind (writable this session).

    Returns:
        HandlerResult(stdout, exit_code).

    """
    argv, env = build_invocation(action, ctx, hp_work_host=hp_dir / "work")
    res = runner.run(argv, binds=[(str(hp_dir), "/hp")], setenv=env)
    return HandlerResult(stdout=res.stdout, exit_code=res.exit_code)
