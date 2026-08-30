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


def run_stage(runner: Runner, task: TaskCode, stage_index: int,
              *, noise: list[list[str]] | None = None) -> Observation:
    prep: list[str] = list(task.setup)
    for stage in task.stages[:stage_index]:
        prep.extend(stage.commands)
    if prep:
        runner.run(["sh", "-c", _script(tuple(prep))])   # PREP: mutate rootfs, discard stdout
    target = task.stages[stage_index]
    # TARGET: capture only the LAST command's stdout, same shell (matches runtime .cmd.out)
    result = runner.run(["sh", "-c", _target_script(target.commands)])
    run_noise(runner, noise)
    obs = capture(runner.rootfs, list(target.observe))
    obs[OUTPUT_KEY] = FileState("file", result.stdout)
    for key in list(obs):
        if key != OUTPUT_KEY and any(key.startswith(prefix) for prefix in target.exclude):
            del obs[key]
    return obs
