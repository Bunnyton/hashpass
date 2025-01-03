from hooks.engine import *

@command(stages=[0, 1])
def cmd(cmd: list, stage: int):
    res = {"before": ["echo \"It is worked, IT IS WORKEEEEED!!!!!!\""]
            , "cmd": [cmd]
            , "after": []}

    return res


@command(cmds=["ls", "sl"], stages=[0, 1])
def cmd_ls(cmd: list, stage: int):
    res = {"before": ["echo \"It is worked, IT IS WORKEEEEED!!!!!!\""]
            , "cmd": [cmd]
            , "after": []}

    return res


@filter()
def filt(data: str, stage: int):
    lines = list()
    for line in data.split('\n'):
        if "bash_history" not in line:
            lines.append(line)

    return "\n".join(lines)
