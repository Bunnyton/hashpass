"""Run a task stage in a Runner and snapshot its Observation (state + own output)."""
from hashpass.canon import FileState, Observation, capture, run_noise
from hashpass.runner.base import Runner
from hashpass.taskcode.model import TaskCode

OUTPUT_KEY = "<output>"


def _script(commands: tuple[str, ...]) -> str:
    return "\n".join(commands)


def _target_script(commands: tuple[str, ...]) -> str:
    """Build a script that captures only the LAST command's stdout (§4 semantics)."""
    if not commands:
        return ""
    if len(commands) == 1:
        return commands[0]
    head = "\n".join(commands[:-1])
    return "{\n" + head + "\n} >/dev/null\n" + commands[-1]


def run_stage(runner: Runner, task: TaskCode, stage_index: int,  # noqa: PLR0913
              *, noise: list[list[str]] | None = None,
              override: tuple[str, ...] | None = None,
              user: str | None = None) -> Observation:
    """
    Derive one stage: replay prep, run the target solve, and snapshot the observed state.

    `user` (the recipe's `settings.user`) makes prep + target run under the SAME container
    user the live console uses -- otherwise a `whoami`/`$USER`/`id` reference bakes as
    root and the student's `student` output never matches.  See runner.nspawn.run.
    """
    prep: list[str] = list(task.setup)
    for stage in task.stages[:stage_index]:
        prep.extend(stage.commands)
    if prep:
        prep_res = runner.run(["sh", "-c", _script(tuple(prep))], user=user)   # PREP: mutate rootfs
        if prep_res.exit_code != 0:
            msg = (f"stage {stage_index} prep failed (exit {prep_res.exit_code}): "
                   f"{prep_res.stderr.strip() or prep_res.stdout.strip()!r}")
            raise RuntimeError(msg)
    target = task.stages[stage_index]
    # TARGET: capture only the LAST command's stdout, same shell (matches runtime .cmd.out).
    # `override` runs an ALTERNATIVE solution (a `variant`) as the target; prep/observe unchanged.
    commands = override if override is not None else target.commands
    result = runner.run(["sh", "-c", _target_script(commands)], user=user)
    if result.exit_code != 0:
        # A failed solve means the reference is being derived from a broken run -- surface it
        # instead of silently canonicalizing whatever state the failed nspawn left behind.
        msg = (f"stage {stage_index} solve failed (exit {result.exit_code}): "
               f"{result.stderr.strip() or result.stdout.strip()!r}")
        raise RuntimeError(msg)
    run_noise(runner, noise)
    obs = capture(runner.rootfs, list(target.observe), bool_observe=list(target.observe_bool))
    obs[OUTPUT_KEY] = FileState("file", result.stdout)
    for key in list(obs):
        if key != OUTPUT_KEY and any(key.startswith(prefix) for prefix in target.exclude):
            del obs[key]
    return obs
