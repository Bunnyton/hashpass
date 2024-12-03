import hooks

# Словарь для регистрации команд
cmd_hooks = {"common_handlers": [], "handlers": []}
filter_hooks =  {"common_handlers": None, "handlers": []}


def common_command(stages=None):
    def inner_decorator(handler):
        def decorator(cmd, stage: int):
            cmd_hooks["common_handlers"].append({"stages": stages, "handler": handler})
            return handler
        return decorator
    return inner_decorator


def common_filter(stages=None):
    def inner_decorator(handler):
        def decorator(cmd, stage: int):
            filter_hooks["common_handlers"].append({"stages": stages, "handler": handler})
            return handler
        return decorator
    return inner_decorator


def command(cmds: list, stages=None):
    def inner_decorator(handler):
        def decorator(cmd, stage: int):
            cmd_hooks["handlers"].append({"cmds": cmds, "stages": stages, "handler": handler})
            return handler
        return decorator
    return inner_decorator


def filter(cmds: list, stages=None):
    def inner_decorator(handler):
        def decorator(cmd, stage: int):
            filter_hooks["handlers"].append({"cmds": cmds, "stages": stages, "handler": handler})
            return handler
        return decorator
    return inner_decorator


def cmd_hook(cmd, stage: int):
    res = list()
    for ch in cmd_hooks["common_handlers"]:
        if ch["stages"] is None or stage in ch["stages"]:
            res.append(ch["handler"](cmd, stage))

    for h in cmd_hooks["handlers"]:
        if cmd in h["cmds"]:
            if h["stages"] is None or stage in h["stages"]:
                res.append(h["handler"](cmd, stage))

    return res

