import hooks
import importlib



# Словарь для регистрации команд
cmd_hooks = {"common_handlers": [], "handlers": []} #FIXME add functional to dynamically update code
filter_hooks =  {"common_handlers": [], "handlers": []} 


def command(cmds=None, stages=None):
    def register(handler):
        if cmds is None:
            cmd_hooks["common_handlers"].append({"stages": stages, "handler": handler})

        else:
            cmd_hooks["handlers"].append({"cmds": cmds, "stages": stages, "handler": handler})
    return register


def filter(cmds=None, stages=None):
    def register(handler):
        if cmds is None:
            filter_hooks["common_handlers"].append({"stages": stages, "handler": handler})

        else:
            filter_hooks["handlers"].append({"cmds": cmds, "stages": stages, "handler": handler})
    return register


def cmd_hook(cmd: str, stage: int):
    res = {"before": [],
            "cmd": [cmd],
            "after": []}

    for ch in cmd_hooks["common_handlers"]:
        if ch["stages"] is None or stage in ch["stages"]:
            if res["cmd"]:
                r = ch["handler"](cmd, stage)
                if r["before"]:
                    res["before"].extend(r["before"])
                if r["after"]:
                    res["after"].extend(r["after"])
                res["cmd"] = r["cmd"]

    for h in cmd_hooks["handlers"]:
        if cmd in h["cmds"]:
            if h["stages"] is None or stage in h["stages"]:
                if res["cmd"]:
                    r = h["handler"](cmd, stage)
                    if r["before"]:
                        res["before"].extend(r["before"])
                    if r["after"]:
                        res["after"].extend(r["after"])
                    res["cmd"] = r["cmd"]

    return res



def filter_hook(cmd: str, data: str, stage: int):
    filter_data = data
    for ch in filter_hooks["common_handlers"]:
        if ch["stages"] is None or stage in ch["stages"]:
            filter_data = ch["handler"](cmd, filter_data, stage)

    for h in filter_hooks["handlers"]:
        if cmd in h["cmds"]:
            if h["stages"] is None or stage in h["stages"]:
                filter_data = h["handler"](cmd, filter_data, stage)

    return filter_data

