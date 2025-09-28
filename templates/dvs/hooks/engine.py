import hooks
import importlib



# Словарь для регистрации команд
cmd_hooks_handlers = list() #FIXME add functional to dynamically update code
filter_hooks = list() 
check_hooks = list()


def command(stages=None):
    def register(handler):
        cmd_hooks.append({"stages": stages, "handler": handler})
    return register


def filter(stages=None):
    def register(handler):
        filter_hooks.append({"stages": stages, "handler": handler})
    return register


def check(stages=None):
    def register(handler):
        check_hooks.append({"stages": stages, "handler": handler})
    return register


def cmd_hook(cmd: str, stage: int):
    res = {"before": [],
            "cmd": [cmd],
            "after": []}

    for ch in cmd_hooks:
        if ch["stages"] is None or stage in ch["stages"]:
            if res["cmd"]:
                r = ch["handler"](cmd, stage)
                if r["before"]:
                    res["before"].extend(r["before"])
                if r["after"]:
                    res["after"].extend(r["after"])
                res["cmd"] = r["cmd"]

    return res


def filter_hook(cmd: str, data: str, stage: int):
    filter_data = data
    for ch in filter_hooks:
        if ch["stages"] is None or stage in ch["stages"]:
            filter_data = ch["handler"](cmd, filter_data, stage)

    return filter_data


def check_hook(cmd: str, stage: int):
    for ch in check_hooks:
        if ch["stages"] is None or stage in ch["stages"]:
            check_res = ch["handler"](cmd, stage)
            if check_res is not None:
                return check_res

    return None
